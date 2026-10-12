"""
SocialLite - Group & 1-to-1 Messaging GUI
Modern CustomTkinter-based interface with multi-user group chat support,
live member presence tracking, and built-in Pinggy SSH Internet Tunneling.
"""

import customtkinter as ctk
from tkinter import messagebox
import queue
import time
import hashlib
from datetime import datetime

from network import NetworkManager, get_local_ip
from tunnel import PinggyTunnelManager, get_pinggy_command, parse_connection_target, is_ssh_available, fetch_pinggy_url

# Appearance settings
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Theme Color Constants
COLOR_BG = "#0b1120"           # Dark deep background
COLOR_CARD = "#172033"         # Elevated panel card
COLOR_SUB_CARD = "#0f172a"     # Sub-panel card
COLOR_SENT = "#1d4ed8"         # Sent message bubble (Royal Blue)
COLOR_RECV = "#334155"         # Received message bubble (Slate)
COLOR_SYSTEM = "#1e293b"       # System pill
COLOR_TEXT_MAIN = "#f8fafc"    # Bright white text
COLOR_TEXT_MUTED = "#94a3b8"   # Secondary text
COLOR_GREEN = "#10b981"        # Connected indicator
COLOR_YELLOW = "#f59e0b"       # Waiting / connecting indicator
COLOR_RED = "#ef4444"          # Offline / error indicator
COLOR_PURPLE = "#7c3aed"       # Pinggy tunnel purple
COLOR_PURPLE_HOVER = "#6d28d9"

# Distinct avatar colors for different group members
MEMBER_COLORS = [
    "#38bdf8",  # Sky blue
    "#34d399",  # Emerald
    "#fbbf24",  # Amber
    "#f472b6",  # Pink
    "#a78bfa",  # Violet
    "#fb923c",  # Orange
    "#2dd4bf",  # Teal
    "#e879f9",  # Fuchsia
]


def get_sender_color(sender: str) -> str:
    """Consistently assign a distinct pleasant color based on username."""
    idx = int(hashlib.md5(sender.encode("utf-8")).hexdigest(), 16) % len(MEMBER_COLORS)
    return MEMBER_COLORS[idx]


class SocialLiteGUI:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("SocialLite - Multi-User Group Messenger")
        self.root.geometry("960x760")
        self.root.minsize(800, 620)
        self.root.configure(fg_color=COLOR_BG)

        # Networking & Tunnel Managers with Group Chat Callbacks
        self.event_queue = queue.Queue()
        self.network = NetworkManager(
            on_connected=self._on_net_connected,
            on_message=self._on_net_message,
            on_user_list_changed=self._on_net_user_list_changed,
            on_system_notice=self._on_net_system_notice,
            on_disconnected=self._on_net_disconnected,
            on_error=self._on_net_error
        )
        self.tunnel_manager = PinggyTunnelManager()

        self.local_ip = get_local_ip()
        self.username = ctk.StringVar(value="User")
        self.mode = ctk.StringVar(value="Host (Group Admin)")  # "Host (Group Admin)" or "Connect (Join Group)"
        self.host_ip = ctk.StringVar(value="127.0.0.1")
        self.port = ctk.StringVar(value="5001")
        self.status_text = ctk.StringVar(value="Offline - Not in Group")
        self.public_pinggy_url = ctk.StringVar(value="")

        # Member list tracking
        self.members_list = []

        # Auto-parse target host if user pastes full URL with port
        self.host_ip.trace_add("write", self._on_target_changed)

        self._build_ui()
        self._update_mode_ui()

        # Start event loop listener for thread-safe GUI updates
        self.root.after(50, self._process_network_queue)
        # Start background polling to auto-fetch Pinggy URL
        self.root.after(1000, self._poll_auto_fetch_pinggy_url)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 1. Top Connection Card
        top_card = ctk.CTkFrame(self.root, fg_color=COLOR_CARD, corner_radius=14)
        top_card.pack(fill="x", padx=16, pady=(14, 8))

        # Header Title & Status Row
        header_row = ctk.CTkFrame(top_card, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(12, 10))

        title_lbl = ctk.CTkLabel(
            header_row,
            text="💬 SocialLite",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        )
        title_lbl.pack(side="left")

        subtitle_lbl = ctk.CTkLabel(
            header_row,
            text="Multi-User Group Messenger",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED
        )
        subtitle_lbl.pack(side="left", padx=(10, 0), pady=(4, 0))

        # Status Pill on the right
        status_pill = ctk.CTkFrame(header_row, fg_color=COLOR_SUB_CARD, corner_radius=20)
        status_pill.pack(side="right")

        self.status_dot = ctk.CTkLabel(
            status_pill,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color=COLOR_RED
        )
        self.status_dot.pack(side="left", padx=(10, 4), pady=4)

        self.status_lbl = ctk.CTkLabel(
            status_pill,
            textvariable=self.status_text,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MAIN
        )
        self.status_lbl.pack(side="left", padx=(0, 12), pady=4)

        # Connection Controls Row
        controls_frame = ctk.CTkFrame(top_card, fg_color="transparent")
        controls_frame.pack(fill="x", padx=16, pady=(0, 10))

        # Username
        ctk.CTkLabel(controls_frame, text="Your Name:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.user_entry = ctk.CTkEntry(controls_frame, textvariable=self.username, width=110, height=32, corner_radius=8)
        self.user_entry.grid(row=0, column=1, padx=(0, 12))

        # Mode Segmented Button
        ctk.CTkLabel(controls_frame, text="Role:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.mode_btn = ctk.CTkSegmentedButton(
            controls_frame,
            values=["Host (Group Admin)", "Connect (Join Group)"],
            variable=self.mode,
            command=lambda v: self._update_mode_ui(),
            height=32,
            corner_radius=8
        )
        self.mode_btn.grid(row=0, column=3, padx=(0, 12))

        # Target IP / Host
        self.ip_lbl = ctk.CTkLabel(controls_frame, text="Bind IP:", font=ctk.CTkFont(size=12, weight="bold"))
        self.ip_lbl.grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.ip_entry = ctk.CTkEntry(controls_frame, textvariable=self.host_ip, width=220, height=32, corner_radius=8)
        self.ip_entry.grid(row=0, column=5, padx=(0, 10))

        # Port
        ctk.CTkLabel(controls_frame, text="Port:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=6, sticky="w", padx=(0, 4))
        self.port_entry = ctk.CTkEntry(controls_frame, textvariable=self.port, width=68, height=32, corner_radius=8)
        self.port_entry.grid(row=0, column=7, padx=(0, 12))

        # Action Button (Start Group / Join Group)
        self.action_btn = ctk.CTkButton(
            controls_frame,
            text="Start Group",
            command=self._toggle_connection,
            width=120,
            height=32,
            corner_radius=8,
            font=ctk.CTkFont(weight="bold")
        )
        self.action_btn.grid(row=0, column=8, padx=(0, 0))

        # 1.1 Pinggy Global Internet Assistant Subpanel
        self.assistant_frame = ctk.CTkFrame(top_card, fg_color=COLOR_SUB_CARD, corner_radius=10)
        self.assistant_frame.pack(fill="x", padx=16, pady=(0, 12))

        # Host Assistant Box (2 Rows: Command Launcher & Shareable Public Link Box)
        self.host_assistant_box = ctk.CTkFrame(self.assistant_frame, fg_color="transparent")
        self.host_assistant_box.pack(fill="x", padx=10, pady=6)

        # Row 1: Tunnel Command & Launcher
        h_row1 = ctk.CTkFrame(self.host_assistant_box, fg_color="transparent")
        h_row1.pack(fill="x", pady=(2, 6))

        host_tag = ctk.CTkLabel(
            h_row1,
            text="🌐 Group Tunnel (Pinggy):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#c084fc"
        )
        host_tag.pack(side="left", padx=(0, 8))

        self.tunnel_cmd_lbl = ctk.CTkLabel(
            h_row1,
            text="ssh -p 443 -R0:127.0.0.1:5001 tcp@a.pinggy.io",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#090d16",
            corner_radius=6,
            text_color="#38bdf8",
            padx=10,
            pady=4
        )
        self.tunnel_cmd_lbl.pack(side="left", padx=(0, 10))

        self.copy_cmd_btn = ctk.CTkButton(
            h_row1,
            text="📋 Copy Command",
            command=self._copy_pinggy_command,
            width=120,
            height=28,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569"
        )
        self.copy_cmd_btn.pack(side="left", padx=(0, 8))

        self.launch_tunnel_btn = ctk.CTkButton(
            h_row1,
            text="🚀 Launch Tunnel",
            command=self._toggle_pinggy_tunnel,
            width=120,
            height=28,
            corner_radius=6,
            fg_color=COLOR_PURPLE,
            hover_color=COLOR_PURPLE_HOVER
        )
        self.launch_tunnel_btn.pack(side="left")

        # Row 2: Extra Pinggy Public Link Input Box & Copy for Members (Better UX)
        h_row2 = ctk.CTkFrame(self.host_assistant_box, fg_color="transparent")
        h_row2.pack(fill="x", pady=(2, 2))

        link_tag = ctk.CTkLabel(
            h_row2,
            text="🔗 Public Link for Members:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        link_tag.pack(side="left", padx=(0, 8))

        self.public_link_entry = ctk.CTkEntry(
            h_row2,
            textvariable=self.public_pinggy_url,
            placeholder_text="Paste Pinggy URL here (e.g. tcp://rndnj-xxx.a.free.pinggy.online:37315)",
            width=360,
            height=28,
            corner_radius=6
        )
        self.public_link_entry.pack(side="left", padx=(0, 8))

        self.paste_public_link_btn = ctk.CTkButton(
            h_row2,
            text="📥 Paste URL",
            command=self._paste_public_pinggy_url,
            width=90,
            height=28,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569"
        )
        self.paste_public_link_btn.pack(side="left", padx=(0, 8))

        self.copy_public_link_btn = ctk.CTkButton(
            h_row2,
            text="📋 Copy Link for Members",
            command=self._copy_public_pinggy_url,
            width=165,
            height=28,
            corner_radius=6,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(weight="bold")
        )
        self.copy_public_link_btn.pack(side="left")

        # Client Assistant Box
        self.client_assistant_box = ctk.CTkFrame(self.assistant_frame, fg_color="transparent")

        client_tag = ctk.CTkLabel(
            self.client_assistant_box,
            text="🌐 Join Remote Group via Internet:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#60a5fa"
        )
        client_tag.pack(side="left", padx=(0, 8))

        paste_hint = ctk.CTkLabel(
            self.client_assistant_box,
            text="Paste Host's Pinggy address (e.g. tcp://rndnj-xxx.a.free.pinggy.online:37315)",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        )
        paste_hint.pack(side="left", padx=(0, 12))

        self.paste_btn = ctk.CTkButton(
            self.client_assistant_box,
            text="📋 Paste from Clipboard",
            command=self._paste_clipboard_target,
            width=150,
            height=28,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569"
        )
        self.paste_btn.pack(side="left")

        # 2. Main Middle Area: Chat Feed (Left) + Group Members Sidebar (Right)
        middle_container = ctk.CTkFrame(self.root, fg_color="transparent")
        middle_container.pack(fill="both", expand=True, padx=16, pady=4)

        # 2.1 Left: Chat Feed
        chat_box = ctk.CTkFrame(middle_container, fg_color="transparent")
        chat_box.pack(side="left", fill="both", expand=True)

        self.chat_scroll = ctk.CTkScrollableFrame(
            chat_box,
            fg_color=COLOR_BG,
            corner_radius=12,
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569"
        )
        self.chat_scroll.pack(fill="both", expand=True)

        # 2.2 Right: Group Members Sidebar
        self.sidebar_card = ctk.CTkFrame(middle_container, fg_color=COLOR_CARD, corner_radius=12, width=200)
        self.sidebar_card.pack(side="right", fill="y", padx=(10, 0))
        self.sidebar_card.pack_propagate(False)

        # Sidebar Header
        self.member_count_lbl = ctk.CTkLabel(
            self.sidebar_card,
            text="👥 Members (0)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        )
        self.member_count_lbl.pack(padx=12, pady=(12, 6), anchor="w")

        # Sidebar Member List
        self.members_scroll = ctk.CTkScrollableFrame(
            self.sidebar_card,
            fg_color=COLOR_SUB_CARD,
            corner_radius=8,
            scrollbar_button_color="#334155"
        )
        self.members_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 3. Bottom Input Card
        bottom_card = ctk.CTkFrame(self.root, fg_color=COLOR_CARD, corner_radius=14)
        bottom_card.pack(fill="x", padx=16, pady=(6, 14))

        input_row = ctk.CTkFrame(bottom_card, fg_color="transparent")
        input_row.pack(fill="x", padx=12, pady=10)

        self.msg_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="Start or join a group to begin chatting...",
            height=40,
            corner_radius=10,
            font=ctk.CTkFont(size=12)
        )
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.msg_entry.bind("<Return>", lambda e: self._send_message())
        self.msg_entry.configure(state="disabled")

        self.send_btn = ctk.CTkButton(
            input_row,
            text="Send ➤",
            command=self._send_message,
            width=90,
            height=40,
            corner_radius=10,
            font=ctk.CTkFont(weight="bold")
        )
        self.send_btn.pack(side="right")
        self.send_btn.configure(state="disabled")

        # Initial Welcome Message
        self._add_system_message("Welcome to SocialLite Group Chat! Host a room or join one via IP / Pinggy.")

    def _on_target_changed(self, *args):
        """Auto-parse port if a full URL/port string is typed or pasted in Connect mode."""
        if "Connect" not in self.mode.get() or self.network.is_connected:
            return

        raw = self.host_ip.get().strip()
        if "://" in raw or (":" in raw and not raw.endswith(":")):
            host, port = parse_connection_target(raw, int(self.port.get() or "5001"))
            if host != raw:
                self.host_ip.set(host)
                self.port.set(str(port))

    def _paste_clipboard_target(self):
        """Paste from system clipboard and auto-split host and port."""
        try:
            clip = self.root.clipboard_get().strip()
            if clip:
                host, port = parse_connection_target(clip, 5001)
                self.host_ip.set(host)
                self.port.set(str(port))
                self._add_system_message(f"Parsed address from clipboard: Host='{host}', Port='{port}'")
        except Exception as e:
            messagebox.showinfo("Clipboard", f"Could not read clipboard: {e}")

    def _copy_pinggy_command(self):
        """Copy the exact Pinggy tunnel command to clipboard."""
        port = int(self.port.get().strip() or "5001")
        cmd = get_pinggy_command(port)
        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        self._add_system_message(f"📋 Copied Pinggy command to clipboard: {cmd}")

    def _paste_public_pinggy_url(self):
        """Paste Pinggy public URL from clipboard into the Host extra input box."""
        try:
            clip = self.root.clipboard_get().strip()
            if clip:
                import re
                m = re.search(r'(tcp://[a-zA-Z0-9.-]+:\d+|[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*:\d+)', clip)
                extracted = m.group(1) if m else clip
                self.public_pinggy_url.set(extracted)
                self._add_system_message(f"🔗 Pinggy public link saved: {extracted}. Click 'Copy Link for Members' anytime to share!")
        except Exception as e:
            messagebox.showinfo("Clipboard", f"Could not read clipboard: {e}")

    def _copy_public_pinggy_url(self):
        """Copy the Host Pinggy public URL to clipboard for sending to members."""
        url = self.public_pinggy_url.get().strip()
        if not url:
            messagebox.showwarning(
                "No Public Link Found",
                "Please paste or enter your Pinggy public URL into the input box first!\n(You can copy it from the Pinggy tunnel console window)."
            )
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._add_system_message(f"📋 Copied Pinggy link to clipboard: {url}\nSend this link to your group members so they can join!")

    def _toggle_pinggy_tunnel(self):
        """Launch or stop Pinggy tunnel console from the GUI."""
        if self.tunnel_manager.is_running:
            self.tunnel_manager.stop_tunnel()
            self.launch_tunnel_btn.configure(text="🚀 Launch Tunnel", fg_color=COLOR_PURPLE, hover_color=COLOR_PURPLE_HOVER)
            self._add_system_message("Pinggy tunnel stopped.")
        else:
            port = int(self.port.get().strip() or "5001")
            ok, msg = self.tunnel_manager.start_tunnel(local_port=port, open_console=True)
            if ok:
                self.launch_tunnel_btn.configure(text="⏹️ Stop Tunnel", fg_color=COLOR_RED, hover_color="#dc2626")
                self._add_system_message("🚀 Pinggy tunnel console launched!\nCopy the 'tcp://...' link from the console, then click '📥 Paste URL' above to easily share with members.")
            else:
                messagebox.showerror("Tunnel Error", msg)

    def _update_mode_ui(self):
        """Update labels, buttons, and panels based on selected role."""
        if self.network.is_connected or self.network.is_listening:
            return

        if "Host" in self.mode.get():
            self.ip_lbl.configure(text="Bind IP:")
            self.host_ip.set("127.0.0.1")
            self.port.set("5001")
            self.action_btn.configure(text="Start Group", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

            self.client_assistant_box.pack_forget()
            self.host_assistant_box.pack(fill="x", padx=10, pady=8)
            self._update_tunnel_label()
        else:
            self.ip_lbl.configure(text="Target Host:")
            self.host_ip.set("a.pinggy.io")
            self.port.set("5001")
            self.action_btn.configure(text="Join Group", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

            self.host_assistant_box.pack_forget()
            self.client_assistant_box.pack(fill="x", padx=10, pady=8)

    def _update_tunnel_label(self):
        try:
            port = int(self.port.get().strip() or "5001")
        except ValueError:
            port = 5001
        self.tunnel_cmd_lbl.configure(text=get_pinggy_command(port))

    def _poll_auto_fetch_pinggy_url(self):
        """Periodically check if Pinggy public URL has become active via API (after password in CMD) or clipboard."""
        try:
            if "Host" in self.mode.get():
                current_val = self.public_pinggy_url.get().strip()

                # 1. Check local debugger API (becomes active right after entering password in CMD)
                fetched = fetch_pinggy_url(4300)
                if fetched and fetched != current_val:
                    self.public_pinggy_url.set(fetched)
                    try:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(fetched)
                    except Exception:
                        pass
                    self._add_system_message(
                        f"🎉 Pinggy URL auto-fetched from tunnel!\n{fetched}\n(Automatically copied to your clipboard!)"
                    )

                # 2. Check clipboard if user selected/copied text from CMD
                elif not current_val:
                    try:
                        clip = self.root.clipboard_get().strip()
                        if clip and ("tcp://" in clip or "pinggy" in clip):
                            import re
                            m = re.search(r'(tcp://[a-zA-Z0-9.-]+:\d+|[a-zA-Z0-9.-]+\.pinggy[a-zA-Z0-9.-]*:\d+)', clip)
                            if m:
                                url = m.group(1)
                                if url != current_val:
                                    self.public_pinggy_url.set(url)
                                    self._add_system_message(f"🎉 Pinggy URL detected & auto-filled from clipboard:\n{url}")
                    except Exception:
                        pass
        except Exception:
            pass

        # Check again every 1200ms
        self.root.after(1200, self._poll_auto_fetch_pinggy_url)

    def _set_status(self, text: str, color: str):
        self.status_text.set(text)
        self.status_dot.configure(text_color=color)

    def _toggle_connection(self):
        if self.network.is_connected or self.network.is_listening:
            # Disconnect
            self.network.disconnect()
            self._set_status("Offline - Left Group", COLOR_RED)
            self._on_disconnected_ui()
            self._add_system_message("You left / stopped the group chat.")
            return

        port_str = self.port.get().strip()
        if not port_str.isdigit():
            messagebox.showerror("Invalid Port", "Port must be a valid number (e.g. 5001).")
            return
        port = int(port_str)

        raw_ip = self.host_ip.get().strip()
        if not raw_ip:
            messagebox.showerror("Invalid Host", "Please specify an IP address or hostname.")
            return

        host, parsed_port = parse_connection_target(raw_ip, port)
        if parsed_port != port:
            port = parsed_port
            self.port.set(str(port))
            self.host_ip.set(host)

        my_name = self.username.get().strip() or "User"

        if "Host" in self.mode.get():
            # Start multi-user host
            success, msg = self.network.start_host(host, port, username=my_name)
            if success:
                self._set_status(f"Group Active ({host}:{port})", COLOR_GREEN)
                self.action_btn.configure(text="Stop Group", fg_color=COLOR_RED, hover_color="#dc2626")
                self._disable_inputs()
                self.msg_entry.configure(state="normal", placeholder_text="Type a message to group... (Enter to send)")
                self.send_btn.configure(state="normal")
                self.msg_entry.focus()
                self._add_system_message(f"👑 Group Room created by {my_name}! Ready for members to join.")
            else:
                messagebox.showerror("Host Error", f"Could not start group server: {msg}")
        else:
            # Connect as group member
            self._set_status(f"Joining {host}:{port}...", COLOR_YELLOW)
            self.action_btn.configure(text="Cancel", fg_color=COLOR_RED, hover_color="#dc2626")
            self._disable_inputs()
            self.network.connect_to_peer(host, port, username=my_name)

    def _disable_inputs(self):
        self.user_entry.configure(state="disabled")
        self.mode_btn.configure(state="disabled")
        self.ip_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")

    def _enable_inputs(self):
        self.user_entry.configure(state="normal")
        self.mode_btn.configure(state="normal")
        self.ip_entry.configure(state="normal")
        self.port_entry.configure(state="normal")

    def _on_connected_ui(self, peer_addr):
        self._set_status("In Group Chat", COLOR_GREEN)
        self.action_btn.configure(text="Leave Group", fg_color=COLOR_RED, hover_color="#dc2626")
        self.msg_entry.configure(state="normal", placeholder_text="Type a message to group... (Enter to send)")
        self.send_btn.configure(state="normal")
        self.msg_entry.focus()
        self._add_system_message(f"🎉 Connected to the group chat!")

    def _on_disconnected_ui(self):
        self._enable_inputs()
        self._update_mode_ui()
        self.msg_entry.delete(0, "end")
        self.msg_entry.configure(state="disabled", placeholder_text="Start or join a group to begin chatting...")
        self.send_btn.configure(state="disabled")
        self._update_members_display([])

    def _update_members_display(self, users: list):
        """Update the sidebar with current group members."""
        self.members_list = users
        self.member_count_lbl.configure(text=f"👥 Members ({len(users)})")

        # Clear existing member items
        for child in self.members_scroll.winfo_children():
            child.destroy()

        for user in users:
            item_row = ctk.CTkFrame(self.members_scroll, fg_color="transparent")
            item_row.pack(fill="x", pady=2, padx=4)

            # Online dot
            dot = ctk.CTkLabel(item_row, text="●", text_color=COLOR_GREEN, font=ctk.CTkFont(size=10))
            dot.pack(side="left", padx=(2, 6))

            # User name with personalized color
            name_color = get_sender_color(user)
            name_lbl = ctk.CTkLabel(
                item_row,
                text=user,
                font=ctk.CTkFont(size=11, weight="bold" if "(Host)" in user else "normal"),
                text_color=name_color
            )
            name_lbl.pack(side="left", anchor="w")

    def _send_message(self):
        text = self.msg_entry.get().strip()
        if not text:
            return

        if not (self.network.is_connected or self.network.is_listening):
            return

        timestamp = datetime.now().strftime("%I:%M %p")
        sender = self.username.get().strip() or "Me"

        payload = {
            "type": "chat",
            "sender": sender,
            "text": text,
            "timestamp": timestamp
        }

        if self.network.send_message(payload):
            self._add_message(sender="You", text=text, timestamp=timestamp, is_sent=True)
            self.msg_entry.delete(0, "end")
        else:
            messagebox.showwarning("Send Failed", "Message could not be delivered to the group.")

    def _add_message(self, sender: str, text: str, timestamp: str, is_sent: bool):
        """Render modern chat bubble in group feed."""
        bubble_row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        bubble_row.pack(fill="x", pady=4, padx=6)

        bubble_color = COLOR_SENT if is_sent else COLOR_RECV
        align = "e" if is_sent else "w"

        bubble = ctk.CTkFrame(bubble_row, fg_color=bubble_color, corner_radius=14)
        bubble.pack(side="right" if is_sent else "left", anchor=align, padx=4)

        # Header: Sender name with custom color + Timestamp
        header_row = ctk.CTkFrame(bubble, fg_color="transparent")
        header_row.pack(anchor=align, padx=14, pady=(8, 2))

        if is_sent:
            time_lbl = ctk.CTkLabel(header_row, text=f"{timestamp}  •  You", font=ctk.CTkFont(size=10, weight="bold"), text_color="#93c5fd")
            time_lbl.pack(side="right")
        else:
            sender_color = get_sender_color(sender)
            sender_lbl = ctk.CTkLabel(header_row, text=sender, font=ctk.CTkFont(size=11, weight="bold"), text_color=sender_color)
            sender_lbl.pack(side="left", padx=(0, 6))

            time_lbl = ctk.CTkLabel(header_row, text=f"•  {timestamp}", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
            time_lbl.pack(side="left")

        # Body: Message text
        body_lbl = ctk.CTkLabel(
            bubble,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color="#ffffff" if is_sent else "#f1f5f9",
            wraplength=460,
            justify="right" if is_sent else "left"
        )
        body_lbl.pack(anchor=align, padx=14, pady=(0, 8))

        # Auto-scroll to bottom
        self.root.update_idletasks()
        try:
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _add_system_message(self, text: str):
        """Render centered system notification pill in feed."""
        sys_row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        sys_row.pack(fill="x", pady=6)

        pill = ctk.CTkFrame(sys_row, fg_color=COLOR_SYSTEM, corner_radius=12)
        pill.pack(anchor="center")

        lbl = ctk.CTkLabel(
            pill,
            text=f"• {text} •",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color=COLOR_TEXT_MUTED
        )
        lbl.pack(padx=16, pady=4)

        self.root.update_idletasks()
        try:
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    # Thread Callbacks (push to thread-safe queue)
    def _on_net_connected(self, peer_addr):
        self.event_queue.put(("connected", peer_addr))

    def _on_net_message(self, message):
        self.event_queue.put(("message", message))

    def _on_net_user_list_changed(self, user_list):
        self.event_queue.put(("user_list", user_list))

    def _on_net_system_notice(self, notice):
        self.event_queue.put(("notice", notice))

    def _on_net_disconnected(self):
        self.event_queue.put(("disconnected", None))

    def _on_net_error(self, err_msg):
        self.event_queue.put(("error", err_msg))

    def _process_network_queue(self):
        """Process messages received from background network threads safely on main thread."""
        while not self.event_queue.empty():
            try:
                event_type, data = self.event_queue.get_nowait()
                if event_type == "connected":
                    self._on_connected_ui(data)
                elif event_type == "message":
                    if isinstance(data, dict) and data.get("type") == "chat":
                        sender = data.get("sender", "Peer")
                        text = data.get("text", "")
                        timestamp = data.get("timestamp", datetime.now().strftime("%I:%M %p"))
                        self._add_message(sender=sender, text=text, timestamp=timestamp, is_sent=False)
                elif event_type == "user_list":
                    self._update_members_display(data)
                elif event_type == "notice":
                    self._add_system_message(str(data))
                elif event_type == "disconnected":
                    self._set_status("Offline - Left Group", COLOR_RED)
                    self._on_disconnected_ui()
                    self._add_system_message("Disconnected from group.")
                elif event_type == "error":
                    self._add_system_message(f"Network Notice: {data}")
            except queue.Empty:
                break

        # Poll again every 50ms
        self.root.after(50, self._process_network_queue)

    def _on_close(self):
        """Clean shutdown of sockets and tunnel processes."""
        self.network.disconnect()
        self.tunnel_manager.stop_tunnel()
        self.root.destroy()
