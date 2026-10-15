"""
Network communication module for SocialLite Group & 1-to-1 messaging.
Supports multiple simultaneous clients in Host mode (Group Server),
with message broadcasting for group chats, private unicast routing for 1-to-1 direct messaging,
user presence tracking, keepalive heartbeats, and length-prefixed JSON framing.
"""

import socket
import threading
import struct
import json
import time

HEADER_FORMAT = ">I"  # 4 bytes unsigned int (big-endian)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
HEARTBEAT_INTERVAL = 20  # seconds


def get_local_ip() -> str:
    """Detect local LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class NetworkManager:
    def __init__(self,
                 on_connected=None,
                 on_message=None,
                 on_user_list_changed=None,
                 on_system_notice=None,
                 on_disconnected=None,
                 on_error=None):
        self.on_connected = on_connected
        self.on_message = on_message
        self.on_user_list_changed = on_user_list_changed
        self.on_system_notice = on_system_notice
        self.on_disconnected = on_disconnected
        self.on_error = on_error

        self.server_socket = None
        self.client_socket = None
        self.is_connected = False
        self.is_listening = False
        self.mode = None  # 'host' or 'client'
        self.my_username = "User"
        self.host_username = ""

        # Host-mode client registry: {socket: {"addr": addr, "username": str}}
        self.clients = {}
        self._lock = threading.Lock()

        self._listen_thread = None
        self._receive_thread = None
        self._heartbeat_thread = None

    def _find_client_by_username(self, username: str):
        """Lookup a connected client socket by exact or case-insensitive username."""
        with self._lock:
            for sock, info in self.clients.items():
                if info["username"].strip().lower() == username.strip().lower():
                    return sock
        return None

    # ==========================
    # Host Mode (Group Server)
    # ==========================
    def start_host(self, host: str, port: int, username: str = "Host"):
        """Start listening as Group Chat Host for multiple incoming peers."""
        self.disconnect()
        self.mode = 'host'
        self.my_username = username
        self.host_username = username
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((host, port))
            self.server_socket.listen(50)  # Support multiple group members
            self.is_listening = True

            self._listen_thread = threading.Thread(target=self._host_accept_loop, daemon=True)
            self._listen_thread.start()

            # Start heartbeat sender
            self._start_heartbeat()

            if self.on_user_list_changed:
                self.on_user_list_changed([self.my_username], self.my_username)

            return True, f"Listening on {host}:{port}"
        except Exception as e:
            self.disconnect()
            return False, str(e)

    def _host_accept_loop(self):
        """Accept multiple incoming connections and spawn worker thread for each."""
        while self.is_listening:
            try:
                conn, addr = self.server_socket.accept()
                try:
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass

                default_name = f"Peer-{addr[1]}"
                with self._lock:
                    self.clients[conn] = {"addr": addr, "username": default_name}
                    self.is_connected = True

                client_thread = threading.Thread(
                    target=self._host_client_handler,
                    args=(conn, addr),
                    daemon=True
                )
                client_thread.start()

            except Exception as e:
                if self.is_listening:
                    if self.on_error:
                        self.on_error(f"Host accept notice: {e}")
                break

    def _host_client_handler(self, conn: socket.socket, addr):
        """Handle incoming messages from a specific connected group member."""
        try:
            while self.is_listening:
                msg = self._read_framed_message(conn)
                if msg is None:
                    break

                m_type = msg.get("type")

                if m_type == "heartbeat":
                    continue

                elif m_type == "join":
                    # Client announced their username
                    client_name = msg.get("username", f"User-{addr[1]}").strip() or f"User-{addr[1]}"
                    with self._lock:
                        # Close and prune any stale duplicate connections for the same username
                        stale_socks = [
                            s for s, info in self.clients.items()
                            if s != conn and info["username"].strip().lower() == client_name.strip().lower()
                        ]
                        for s in stale_socks:
                            try:
                                s.close()
                            except Exception:
                                pass
                            if s in self.clients:
                                del self.clients[s]

                        if conn in self.clients:
                            self.clients[conn]["username"] = client_name

                    # Announce join
                    join_notice = f"🎉 {client_name} joined the room!"
                    if self.on_system_notice:
                        self.on_system_notice(join_notice)

                    self.broadcast({
                        "type": "system",
                        "text": join_notice
                    })
                    self._host_broadcast_user_list()

                elif m_type in ("chat", "file"):
                    recipient = msg.get("recipient", "group")

                    if recipient == "group":
                        # Group message: display on Host, broadcast to all other clients
                        if self.on_message:
                            self.on_message(msg)
                        self.broadcast(msg, exclude_sock=conn)
                    else:
                        # 1-to-1 Private Message!
                        if recipient.lower() == self.my_username.lower():
                            # Direct message targeted to Host
                            if self.on_message:
                                self.on_message(msg)
                        else:
                            # Direct message routed to another client
                            target_sock = self._find_client_by_username(recipient)
                            if target_sock:
                                try:
                                    self._send_framed(target_sock, msg)
                                except Exception:
                                    self._send_framed(conn, {
                                        "type": "system",
                                        "text": f"Delivery failed: Could not reach {recipient}."
                                    })
                            else:
                                self._send_framed(conn, {
                                    "type": "system",
                                    "text": f"User '{recipient}' is not online."
                                })

        except Exception:
            pass
        finally:
            self._host_remove_client(conn)

    def _host_remove_client(self, conn: socket.socket):
        """Clean up disconnected client and notify room."""
        client_name = "A member"
        with self._lock:
            if conn in self.clients:
                client_name = self.clients[conn]["username"]
                del self.clients[conn]

        try:
            conn.close()
        except Exception:
            pass

        # Only broadcast leave notice if it was a real named user, not a probe
        if not client_name.startswith("Peer-"):
            leave_notice = f"👋 {client_name} left the room."
            if self.on_system_notice:
                self.on_system_notice(leave_notice)

            self.broadcast({"type": "system", "text": leave_notice})
            self._host_broadcast_user_list()

    def _host_broadcast_user_list(self):
        """Broadcast updated user list to all connected members."""
        with self._lock:
            # Only list real named users
            client_names = [info["username"] for info in self.clients.values() if not info["username"].startswith("Peer-")]
        all_users = [self.my_username] + client_names

        if self.on_user_list_changed:
            self.on_user_list_changed(all_users, self.my_username)

        self.broadcast({
            "type": "user_list",
            "users": all_users,
            "host": self.my_username
        })

    def broadcast(self, data: dict, exclude_sock: socket.socket = None):
        """Broadcast framed message to all connected group members."""
        with self._lock:
            # Exclude raw probes and the excluded socket
            client_sockets = [
                s for s, info in self.clients.items()
                if s != exclude_sock and not info["username"].startswith("Peer-")
            ]

        dead_sockets = []
        for s in client_sockets:
            try:
                self._send_framed(s, data)
            except Exception:
                dead_sockets.append(s)

        for s in dead_sockets:
            self._host_remove_client(s)

    # ==========================
    # Client Mode (Group Member)
    # ==========================
    def connect_to_peer(self, host: str, port: int, username: str = "User"):
        """Connect as a member to a remote Group Chat Host."""
        self.disconnect()
        self.mode = 'client'
        self.my_username = username

        def _connect_worker():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(20.0)  # Internet / Pinggy WAN tolerance
                s.connect((host, port))
                s.settimeout(None)

                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass

                with self._lock:
                    self.client_socket = s
                    self.is_connected = True

                # Send join packet with chosen username
                self._send_framed(s, {
                    "type": "join",
                    "username": self.my_username
                })

                if self.on_connected:
                    self.on_connected((host, port))

                # Start heartbeat
                self._start_heartbeat()

                # Receive loop
                self._client_receive_loop()

            except Exception as e:
                self.disconnect()
                if self.on_error:
                    self.on_error(f"Connection failed: {e}")
            finally:
                self._handle_disconnect()

        self._receive_thread = threading.Thread(target=_connect_worker, daemon=True)
        self._receive_thread.start()

    def _client_receive_loop(self):
        """Continuously receive messages from the Host."""
        while self.is_connected and self.client_socket:
            msg = self._read_framed_message(self.client_socket)
            if msg is None:
                break

            m_type = msg.get("type")
            if m_type == "heartbeat":
                continue
            elif m_type in ("chat", "file"):
                if self.on_message:
                    self.on_message(msg)
            elif m_type == "system":
                if self.on_system_notice:
                    self.on_system_notice(msg.get("text", ""))
            elif m_type == "user_list":
                self.host_username = msg.get("host", "")
                if self.on_user_list_changed:
                    self.on_user_list_changed(msg.get("users", []), self.host_username)

    # ==========================
    # Common Helpers
    # ==========================
    def send_message(self, data: dict) -> bool:
        """
        Send a message dictionary.
        If recipient is 'group', broadcasts to all.
        If recipient is a specific username, routes privately as 1-to-1 message!
        """
        recipient = data.get("recipient", "group")

        if self.mode == 'host':
            if not self.is_listening:
                return False

            if recipient == "group":
                self.broadcast(data)
                return True
            else:
                # Host sending 1-to-1 directly to a client
                target_sock = self._find_client_by_username(recipient)
                if target_sock:
                    try:
                        self._send_framed(target_sock, data)
                        return True
                    except Exception as e:
                        if self.on_error:
                            self.on_error(f"Private send error: {e}")
                        return False
                else:
                    if self.on_system_notice:
                        self.on_system_notice(f"User '{recipient}' is not currently connected.")
                    return False
        else:
            # Client sends to host (Host routes to 'group' or specific client)
            if not self.is_connected or not self.client_socket:
                return False
            try:
                self._send_framed(self.client_socket, data)
                return True
            except Exception as e:
                if self.on_error:
                    self.on_error(f"Send error: {e}")
                self.disconnect()
                return False

    def _send_framed(self, sock: socket.socket, data: dict):
        """Send a single framed JSON message over given socket."""
        payload = json.dumps(data).encode("utf-8")
        header = struct.pack(HEADER_FORMAT, len(payload))
        sock.sendall(header + payload)

    def _receive_exact(self, sock: socket.socket, num_bytes: int) -> bytes:
        """Helper to receive exact number of bytes from a socket."""
        buffer = bytearray()
        while len(buffer) < num_bytes:
            chunk = min(65536, num_bytes - len(buffer))
            packet = sock.recv(chunk)
            if not packet:
                return None
            buffer.extend(packet)
        return bytes(buffer)

    def _read_framed_message(self, sock: socket.socket) -> dict:
        """Read and parse 1 framed JSON message."""
        header_data = self._receive_exact(sock, HEADER_SIZE)
        if not header_data:
            return None
        (length,) = struct.unpack(HEADER_FORMAT, header_data)
        payload_data = self._receive_exact(sock, length)
        if not payload_data:
            return None
        return json.loads(payload_data.decode("utf-8"))

    def _start_heartbeat(self):
        """Send periodic keepalives to prevent Pinggy and NAT timeout."""
        def _heartbeat_worker():
            while (self.is_connected or self.is_listening):
                time.sleep(HEARTBEAT_INTERVAL)
                if not (self.is_connected or self.is_listening):
                    break
                try:
                    if self.mode == 'client' and self.client_socket:
                        self._send_framed(self.client_socket, {"type": "heartbeat"})
                    elif self.mode == 'host':
                        self.broadcast({"type": "heartbeat"})
                except Exception:
                    pass

        self._heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()

    def _handle_disconnect(self):
        was_connected = self.is_connected
        self.disconnect()
        if was_connected and self.on_disconnected:
            self.on_disconnected()

    def disconnect(self):
        """Cleanly close all sockets and reset state."""
        self.is_connected = False
        self.is_listening = False

        with self._lock:
            # Close client socket
            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.client_socket.close()
                except Exception:
                    pass
                self.client_socket = None

            # Close all host client connections
            for s in list(self.clients.keys()):
                try:
                    s.close()
                except Exception:
                    pass
            self.clients.clear()

            # Close server socket
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass
                self.server_socket = None
