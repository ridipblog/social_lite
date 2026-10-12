"""
Pinggy Tunnel Integration for SocialLite.
Provides global internet connectivity across different networks (e.g. Assam to Delhi).
Includes automatic URL fetching via Pinggy's local debugger API (port 4300).
"""

import subprocess
import shutil
import re
import os
import sys
import urllib.request
import json

CREATE_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0


def is_ssh_available() -> bool:
    """Check if ssh command is installed."""
    return shutil.which("ssh") is not None


def get_pinggy_command(local_port: int = 5001, server: str = "tcp@a.pinggy.io") -> str:
    """Return the exact command to run Pinggy tunnel with local URL auto-fetch forwarder."""
    return f"ssh -p 443 -L4300:localhost:4300 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R0:127.0.0.1:{local_port} {server}"


def fetch_pinggy_url(port: int = 4300) -> str | None:
    """
    Query Pinggy's local endpoint to automatically fetch the assigned public URL.
    Returns the URL string (e.g. 'tcp://rndnj-xxx.a.free.pinggy.online:37315') or None.
    """
    try:
        url = f"http://127.0.0.1:{port}/urls"
        req = urllib.request.Request(url, headers={"User-Agent": "SocialLite"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                urls = data.get("urls", [])
                for u in urls:
                    if u.startswith("tcp://") or "pinggy" in u:
                        return u
    except Exception:
        pass
    return None


def parse_connection_target(target: str, default_port: int = 5001):
    """
    Parse pasted connection strings.
    Handles:
      - tcp://rndnj-103-170-183-11.a.free.pinggy.online:37315
      - rndnj-103-170-183-11.a.free.pinggy.online:37315
      - a.pinggy.io:45678
      - 192.168.1.5:5001
      - pure hostname or IP with separate port
    """
    raw = target.strip()
    if raw.startswith("tcp://"):
        raw = raw[6:]
    elif raw.startswith("http://"):
        raw = raw[7:]
    elif raw.startswith("https://"):
        raw = raw[8:]

    raw = raw.rstrip("/")

    if ":" in raw:
        parts = raw.split(":")
        host = parts[0].strip()
        port_str = parts[1].strip()
        try:
            port = int(port_str)
            return host, port
        except ValueError:
            return host, default_port
    else:
        return raw, default_port


class PinggyTunnelManager:
    """Manages the background Pinggy SSH process."""

    def __init__(self):
        self.process = None
        self.local_port = 5001

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_tunnel(self, local_port: int = 5001, server: str = "tcp@a.pinggy.io", open_console: bool = True) -> tuple[bool, str]:
        """
        Start Pinggy SSH tunnel with local status endpoint enabled (-L4300:localhost:4300).
        If open_console is True, opens a dedicated console window so the host
        can see the public URL, enter passwords/tokens, and see live traffic directly.
        """
        if not is_ssh_available():
            return False, "OpenSSH client ('ssh') is not found on your system."

        self.stop_tunnel()
        self.local_port = local_port

        cmd = [
            "ssh",
            "-p", "443",
            "-L", "4300:localhost:4300",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            f"-R0:127.0.0.1:{local_port}",
            server
        ]

        try:
            flags = CREATE_NEW_CONSOLE if open_console else 0
            self.process = subprocess.Popen(
                cmd,
                creationflags=flags
            )
            return True, "Pinggy tunnel window launched successfully."
        except Exception as e:
            self.process = None
            return False, f"Failed to start Pinggy tunnel: {e}"

    def stop_tunnel(self):
        """Terminate active Pinggy tunnel process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
