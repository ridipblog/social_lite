"""
SocialLite - Multi-User Group & 1-to-1 Direct Messenger.
Features:
- Built-in SQLite3 database for secure user Registration & Login (zero setup required)
- Persistent chat history for both Group chat and 1-to-1 Direct Messages
- Sidebar switching between Group (# General) and 1-to-1 Direct Messages with friends
- Real-time online member presence tracking & unread message badges
- Pinggy SSH reverse tunnel integration with automatic URL fetching for cross-network connectivity
"""

import os
import shutil
import base64
import threading
import customtkinter as ctk
from tkinter import messagebox, filedialog
import queue
import time
import hashlib
import uuid
from datetime import datetime

import database
from network import NetworkManager, get_local_ip
from tunnel import PinggyTunnelManager, get_pinggy_command, parse_connection_target, is_ssh_available, fetch_pinggy_url

# Dedicated directory for downloaded/shared files
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

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
COLOR_SIDEBAR_ACTIVE = "#2563eb"

# File icon mapping
def get_file_icon(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"]:
        return "🖼️"
    elif ext in [".pdf"]:
        return "📕"
    elif ext in [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]:
        return "📦"
    elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
        return "🎵"
    elif ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"]:
        return "🎬"
    elif ext in [".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".c", ".java", ".sql"]:
        return "💻"
    elif ext in [".doc", ".docx", ".odt", ".rtf"]:
        return "📝"
    elif ext in [".xls", ".xlsx", ".csv"]:
        return "📊"
    elif ext in [".ppt", ".pptx"]:
        return "📑"
    elif ext in [".txt", ".md", ".log"]:
        return "📄"
    elif ext in [".exe", ".msi", ".bat", ".cmd", ".sh"]:
        return "⚙️"
    else:
        return "📎"

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

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
        self.root.title("SocialLite - Group & 1-to-1 Messenger")
        self.root.geometry("1020x780")
        self.root.minsize(860, 640)
        self.root.configure(fg_color=COLOR_BG)

        # Current User State
        self.current_user = None  # Set after login

        # Active conversation: 'group' or a friend's username (e.g. 'Bob')
        self.active_chat = "group"
        self.unread_counts = {}  # {chat_id: int}
        self.seen_msg_ids = set()  # Deduplication registry
        self._is_sending = False  # Debounce lock to prevent double-sends
        self.pending_file = None  # Selected file attachment: {"path": str, "name": str, "size": int}
        self.attach_btn = None
        self.file_preview_frame = None

        # Networking & Tunnel Managers
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
        self.mode = ctk.StringVar(value="Host (Group Admin)")
        self.host_ip = ctk.StringVar(value="127.0.0.1")
        self.port = ctk.StringVar(value="5001")
        self.status_text = ctk.StringVar(value="Offline - Not Connected")
        self.public_pinggy_url = ctk.StringVar(value="")

        # Online friends / members list
        self.online_users = []
        self.room_host = ""

        # Auto-parse target host if user pastes full URL with port
        self.host_ip.trace_add("write", self._on_target_changed)

        # Build initial View (Authentication)
        self.auth_container = None
        self.main_container = None
        self._show_auth_screen()

        # Start event loop listener for thread-safe GUI updates
        self.root.after(50, self._process_network_queue)
        # Start background polling to auto-fetch Pinggy URL
        self.root.after(1000, self._poll_auto_fetch_pinggy_url)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    # Screen 1: Authentication View (Login & Registration via SQLite3)
    # =========================================================================
    def _show_auth_screen(self):
        """Display clean, modern login and registration view."""
        if self.main_container:
            self.main_container.destroy()
            self.main_container = None

        self.auth_container = ctk.CTkFrame(self.root, fg_color=COLOR_BG)
        self.auth_container.pack(fill="both", expand=True)

        # Centered Card Frame
        auth_card = ctk.CTkFrame(self.auth_container, fg_color=COLOR_CARD, corner_radius=18, width=440)
        auth_card.place(relx=0.5, rely=0.5, anchor="center")

        # Header Title
        title_box = ctk.CTkFrame(auth_card, fg_color="transparent")
        title_box.pack(fill="x", padx=30, pady=(28, 12))

        ctk.CTkLabel(
            title_box,
            text="💬 SocialLite",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        ).pack(anchor="center")

        ctk.CTkLabel(
            title_box,
            text="Secure 1-to-1 & Group Messenger • SQLite3 Protected",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED
        ).pack(anchor="center", pady=(4, 0))

        # Tabs: Login vs Register
        self.auth_tabs = ctk.CTkTabview(
            auth_card,
            width=380,
            corner_radius=12,
            fg_color=COLOR_SUB_CARD,
            segmented_button_selected_color=COLOR_SENT,
            segmented_button_selected_hover_color="#1e40af"
        )
        self.auth_tabs.pack(padx=24, pady=(6, 20))

        tab_login = self.auth_tabs.add("Login")
        tab_register = self.auth_tabs.add("Register")

        # --- Login Tab Content ---
        ctk.CTkLabel(tab_login, text="Username:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(12, 2))
        self.login_user_entry = ctk.CTkEntry(tab_login, width=320, height=36, corner_radius=8, placeholder_text="Enter your username")
        self.login_user_entry.pack(padx=16, pady=(0, 10))

        ctk.CTkLabel(tab_login, text="Password:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(4, 2))
        self.login_pwd_entry = ctk.CTkEntry(tab_login, width=320, height=36, corner_radius=8, show="•", placeholder_text="Enter your password")
        self.login_pwd_entry.pack(padx=16, pady=(0, 12))
        self.login_pwd_entry.bind("<Return>", lambda e: self._handle_login())

        self.login_status_lbl = ctk.CTkLabel(tab_login, text="", font=ctk.CTkFont(size=11), text_color=COLOR_RED)
        self.login_status_lbl.pack(padx=16, pady=(0, 8))

        btn_login = ctk.CTkButton(
            tab_login,
            text="Log In ➤",
            command=self._handle_login,
            width=320,
            height=38,
            corner_radius=8,
            font=ctk.CTkFont(weight="bold")
        )
        btn_login.pack(padx=16, pady=(4, 16))

        # --- Register Tab Content ---
        ctk.CTkLabel(tab_register, text="Choose Username:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(10, 2))
        self.reg_user_entry = ctk.CTkEntry(tab_register, width=320, height=34, corner_radius=8, placeholder_text="At least 3 characters")
        self.reg_user_entry.pack(padx=16, pady=(0, 8))

        ctk.CTkLabel(tab_register, text="Create Password:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(2, 2))
        self.reg_pwd_entry = ctk.CTkEntry(tab_register, width=320, height=34, corner_radius=8, show="•", placeholder_text="At least 4 characters")
        self.reg_pwd_entry.pack(padx=16, pady=(0, 8))

        ctk.CTkLabel(tab_register, text="Confirm Password:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(2, 2))
        self.reg_pwd_confirm_entry = ctk.CTkEntry(tab_register, width=320, height=34, corner_radius=8, show="•", placeholder_text="Re-type password")
        self.reg_pwd_confirm_entry.pack(padx=16, pady=(0, 10))
        self.reg_pwd_confirm_entry.bind("<Return>", lambda e: self._handle_register())

        self.reg_status_lbl = ctk.CTkLabel(tab_register, text="", font=ctk.CTkFont(size=11), text_color=COLOR_RED)
        self.reg_status_lbl.pack(padx=16, pady=(0, 6))

        btn_register = ctk.CTkButton(
            tab_register,
            text="Create Account 👤",
            command=self._handle_register,
            width=320,
            height=38,
            corner_radius=8,
            fg_color="#10b981",
            hover_color="#059669",
            font=ctk.CTkFont(weight="bold")
        )
        btn_register.pack(padx=16, pady=(2, 14))

        # Footer note about sqlite3
        ctk.CTkLabel(
            auth_card,
            text="🔒 Powered by built-in Python SQLite3 database (social_lite.db)",
            font=ctk.CTkFont(size=10),
            text_color="#64748b"
        ).pack(pady=(0, 18))

    def _handle_login(self):
        """Validate credentials against SQLite3 database."""
        uname = self.login_user_entry.get().strip()
        pwd = self.login_pwd_entry.get().strip()

        ok, result = database.login_user(uname, pwd)
        if ok:
            self.current_user = result
            self.login_status_lbl.configure(text=f"Welcome back, {result}!", text_color=COLOR_GREEN)
            self.root.after(400, self._show_main_dashboard)
        else:
            self.login_status_lbl.configure(text=result, text_color=COLOR_RED)

    def _handle_register(self):
        """Register new user in SQLite3 database."""
        uname = self.reg_user_entry.get().strip()
        pwd = self.reg_pwd_entry.get().strip()
        confirm = self.reg_pwd_confirm_entry.get().strip()

        if pwd != confirm:
            self.reg_status_lbl.configure(text="Passwords do not match!", text_color=COLOR_RED)
            return

        ok, msg = database.register_user(uname, pwd)
        if ok:
            self.reg_status_lbl.configure(text=msg, text_color=COLOR_GREEN)
            # Pre-fill login tab
            self.login_user_entry.delete(0, "end")
            self.login_user_entry.insert(0, uname)
            self.login_pwd_entry.delete(0, "end")
            self.login_pwd_entry.insert(0, pwd)
            self.root.after(900, lambda: self.auth_tabs.set("Login"))
        else:
            self.reg_status_lbl.configure(text=msg, text_color=COLOR_RED)

    def _handle_logout(self):
        """Disconnect and return to authentication screen."""
        if self.network.is_connected or self.network.is_listening:
            self.network.disconnect()
        self.tunnel_manager.stop_tunnel()
        self.current_user = None
        self.online_users = []
        self.active_chat = "group"
        self._show_auth_screen()

    # =========================================================================
    # Screen 2: Main Chat Dashboard (Group + 1-to-1 DMs with Friends)
    # =========================================================================
    def _show_main_dashboard(self):
        """Build and show the full chat dashboard once logged in."""
        if self.auth_container:
            self.auth_container.destroy()
            self.auth_container = None

        self.main_container = ctk.CTkFrame(self.root, fg_color=COLOR_BG)
        self.main_container.pack(fill="both", expand=True)

        # 1. Top Header & Connection Bar
        top_card = ctk.CTkFrame(self.main_container, fg_color=COLOR_CARD, corner_radius=14)
        top_card.pack(fill="x", padx=16, pady=(12, 6))

        # Row 1: Brand + Logged User Profile + Status Badge
        top_row1 = ctk.CTkFrame(top_card, fg_color="transparent")
        top_row1.pack(fill="x", padx=14, pady=(10, 8))

        # Brand
        title_lbl = ctk.CTkLabel(
            top_row1,
            text="💬 SocialLite",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        )
        title_lbl.pack(side="left")

        # User Profile Pill
        user_pill = ctk.CTkFrame(top_row1, fg_color=COLOR_SUB_CARD, corner_radius=16)
        user_pill.pack(side="left", padx=(14, 0))

        user_dot = ctk.CTkLabel(user_pill, text="●", font=ctk.CTkFont(size=12), text_color=COLOR_GREEN)
        user_dot.pack(side="left", padx=(10, 4), pady=3)

        user_name_lbl = ctk.CTkLabel(
            user_pill,
            text=f"Logged as: {self.current_user}",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        )
        user_name_lbl.pack(side="left", padx=(0, 8), pady=3)

        btn_logout = ctk.CTkButton(
            user_pill,
            text="Logout",
            command=self._handle_logout,
            width=54,
            height=22,
            corner_radius=10,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=10)
        )
        btn_logout.pack(side="left", padx=(0, 6), pady=3)

        # Status Pill on the right
        status_pill = ctk.CTkFrame(top_row1, fg_color=COLOR_SUB_CARD, corner_radius=20)
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

        # Row 2: Connection Controls
        controls_frame = ctk.CTkFrame(top_card, fg_color="transparent")
        controls_frame.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(controls_frame, text="Role:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.mode_btn = ctk.CTkSegmentedButton(
            controls_frame,
            values=["Host (Group Admin)", "Connect (Join Group)"],
            variable=self.mode,
            command=lambda v: self._update_mode_ui(),
            height=30,
            corner_radius=8
        )
        self.mode_btn.grid(row=0, column=1, padx=(0, 12))

        self.ip_lbl = ctk.CTkLabel(controls_frame, text="Bind IP:", font=ctk.CTkFont(size=12, weight="bold"))
        self.ip_lbl.grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.ip_entry = ctk.CTkEntry(controls_frame, textvariable=self.host_ip, width=220, height=30, corner_radius=8)
        self.ip_entry.grid(row=0, column=3, padx=(0, 10))

        ctk.CTkLabel(controls_frame, text="Port:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.port_entry = ctk.CTkEntry(controls_frame, textvariable=self.port, width=64, height=30, corner_radius=8)
        self.port_entry.grid(row=0, column=5, padx=(0, 12))

        self.action_btn = ctk.CTkButton(
            controls_frame,
            text="Start Group",
            command=self._toggle_connection,
            width=120,
            height=30,
            corner_radius=8,
            font=ctk.CTkFont(weight="bold")
        )
        self.action_btn.grid(row=0, column=6, padx=(0, 0))

        # Row 3: Pinggy Assistant Subpanel
        self.assistant_frame = ctk.CTkFrame(top_card, fg_color=COLOR_SUB_CARD, corner_radius=10)
        self.assistant_frame.pack(fill="x", padx=14, pady=(0, 10))

        # Host Assistant Box
        self.host_assistant_box = ctk.CTkFrame(self.assistant_frame, fg_color="transparent")
        self.host_assistant_box.pack(fill="x", padx=8, pady=6)

        # Host Row 1
        h_row1 = ctk.CTkFrame(self.host_assistant_box, fg_color="transparent")
        h_row1.pack(fill="x", pady=(2, 4))

        ctk.CTkLabel(h_row1, text="🌐 Group Tunnel (Pinggy):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#c084fc").pack(side="left", padx=(0, 8))

        self.tunnel_cmd_lbl = ctk.CTkLabel(
            h_row1,
            text="ssh -p 443 -L4300:localhost:4300 -o StrictHostKeyChecking=no -R0:127.0.0.1:5001 tcp@a.pinggy.io",
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color="#090d16",
            corner_radius=6,
            text_color="#38bdf8",
            padx=8,
            pady=3
        )
        self.tunnel_cmd_lbl.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            h_row1,
            text="📋 Copy Cmd",
            command=self._copy_pinggy_command,
            width=90,
            height=26,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=10)
        ).pack(side="left", padx=(0, 6))

        self.launch_tunnel_btn = ctk.CTkButton(
            h_row1,
            text="🚀 Launch Tunnel",
            command=self._toggle_pinggy_tunnel,
            width=110,
            height=26,
            corner_radius=6,
            fg_color=COLOR_PURPLE,
            hover_color=COLOR_PURPLE_HOVER,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.launch_tunnel_btn.pack(side="left")

        # Host Row 2: Public link auto-fill
        h_row2 = ctk.CTkFrame(self.host_assistant_box, fg_color="transparent")
        h_row2.pack(fill="x", pady=(2, 2))

        ctk.CTkLabel(h_row2, text="🔗 Public Link for Members:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8").pack(side="left", padx=(0, 8))

        self.public_link_entry = ctk.CTkEntry(
            h_row2,
            textvariable=self.public_pinggy_url,
            placeholder_text="Auto-fetches when tunnel launches...",
            width=360,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11)
        )
        self.public_link_entry.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            h_row2,
            text="📥 Paste",
            command=self._paste_public_pinggy_url,
            width=65,
            height=26,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=10)
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            h_row2,
            text="📋 Copy Link for Friends",
            command=self._copy_public_pinggy_url,
            width=150,
            height=26,
            corner_radius=6,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="left")

        # Client Assistant Box
        self.client_assistant_box = ctk.CTkFrame(self.assistant_frame, fg_color="transparent")
        c_row = ctk.CTkFrame(self.client_assistant_box, fg_color="transparent")
        c_row.pack(fill="x", padx=8, pady=6)

        ctk.CTkLabel(c_row, text="🌐 Join Global Group via Internet:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(c_row, text="Paste Host's Pinggy URL (tcp://...):", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            c_row,
            text="📋 Paste from Clipboard",
            command=self._paste_clipboard_target,
            width=150,
            height=26,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11)
        ).pack(side="left")

        # 2. Main Middle Area: Split View (Left Sidebar: Chats/Friends | Right Area: Active Chat)
        middle_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        middle_container.pack(fill="both", expand=True, padx=16, pady=4)

        # 2.1 Left Sidebar: Channels & Friends
        self.sidebar_card = ctk.CTkFrame(middle_container, fg_color=COLOR_CARD, corner_radius=12, width=240)
        self.sidebar_card.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar_card.pack_propagate(False)

        # Sidebar Header
        sidebar_hdr = ctk.CTkFrame(self.sidebar_card, fg_color="transparent")
        sidebar_hdr.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(sidebar_hdr, text="CHANNELS & FRIENDS", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w")

        # Group Channel Button (# General)
        self.group_chat_btn = ctk.CTkButton(
            self.sidebar_card,
            text="👥 # General (Group)",
            anchor="w",
            command=lambda: self._select_conversation("group"),
            height=36,
            corner_radius=8,
            fg_color=COLOR_SIDEBAR_ACTIVE,
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.group_chat_btn.pack(fill="x", padx=10, pady=(2, 10))

        # Direct Messages Header
        dm_hdr = ctk.CTkFrame(self.sidebar_card, fg_color="transparent")
        dm_hdr.pack(fill="x", padx=12, pady=(4, 4))
        self.friends_count_lbl = ctk.CTkLabel(
            dm_hdr,
            text="DIRECT MESSAGES (0)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLOR_TEXT_MUTED
        )
        self.friends_count_lbl.pack(anchor="w")

        # Friends Scrollable List
        self.friends_scroll = ctk.CTkScrollableFrame(
            self.sidebar_card,
            fg_color=COLOR_SUB_CARD,
            corner_radius=8,
            scrollbar_button_color="#334155"
        )
        self.friends_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 2.2 Right Area: Active Chat Header, Messages Scroll, Input Box
        chat_box = ctk.CTkFrame(middle_container, fg_color=COLOR_CARD, corner_radius=12)
        chat_box.pack(side="right", fill="both", expand=True)

        # Chat Top Header
        self.chat_header_frame = ctk.CTkFrame(chat_box, fg_color=COLOR_SUB_CARD, corner_radius=10, height=44)
        self.chat_header_frame.pack(fill="x", padx=10, pady=(10, 6))
        self.chat_header_frame.pack_propagate(False)

        self.chat_title_lbl = ctk.CTkLabel(
            self.chat_header_frame,
            text="👥 Group Chat (# General)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLOR_TEXT_MAIN
        )
        self.chat_title_lbl.pack(side="left", padx=14)

        self.chat_subtitle_lbl = ctk.CTkLabel(
            self.chat_header_frame,
            text="Messages are visible to all connected members",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.chat_subtitle_lbl.pack(side="left", padx=(0, 14))

        # Chat Messages Scroll Area
        self.chat_scroll = ctk.CTkScrollableFrame(
            chat_box,
            fg_color=COLOR_BG,
            corner_radius=10,
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569"
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=10, pady=2)

        # File Attachment Preview Banner (Above input_row, hidden until file selected)
        self.file_preview_frame = ctk.CTkFrame(chat_box, fg_color="#1e293b", corner_radius=8, height=36)
        self.file_preview_lbl = ctk.CTkLabel(
            self.file_preview_frame,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.file_preview_lbl.pack(side="left", padx=12, pady=5)
        self.file_remove_btn = ctk.CTkButton(
            self.file_preview_frame,
            text="✕ Cancel",
            command=self._cancel_attached_file,
            width=70,
            height=26,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#ef4444",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.file_remove_btn.pack(side="right", padx=8, pady=5)

        # Bottom Input Area
        self.input_row = ctk.CTkFrame(chat_box, fg_color="transparent")
        self.input_row.pack(fill="x", padx=10, pady=(6, 10))

        self.attach_btn = ctk.CTkButton(
            self.input_row,
            text="📎 File",
            command=self._on_attach_file_clicked,
            width=70,
            height=40,
            corner_radius=10,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.attach_btn.pack(side="left", padx=(0, 8))
        self.attach_btn.configure(state="disabled")

        self.msg_entry = ctk.CTkEntry(
            self.input_row,
            placeholder_text="Start or join a group to start messaging...",
            height=40,
            corner_radius=10,
            font=ctk.CTkFont(size=12)
        )
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.msg_entry.bind("<Return>", self._on_return_pressed)
        self.msg_entry.configure(state="disabled")

        self.send_btn = ctk.CTkButton(
            self.input_row,
            text="Send ➤",
            command=self._send_message,
            width=88,
            height=40,
            corner_radius=10,
            font=ctk.CTkFont(weight="bold")
        )
        self.send_btn.pack(side="right")
        self.send_btn.configure(state="disabled")

        # Initial Setup
        self._update_mode_ui()
        self._load_active_chat_history()

    def _on_attach_file_clicked(self):
        """Open file dialog to attach and share any file in group or 1-to-1."""
        if not (self.network.is_connected or self.network.is_listening):
            messagebox.showinfo("Offline", "Please start or join a group room to share files.")
            return

        file_path = filedialog.askopenfilename(title="Select File to Share")
        if not file_path:
            return

        file_size = os.path.getsize(file_path)
        if file_size > 40 * 1024 * 1024:
            messagebox.showwarning(
                "File Too Large",
                "Please choose a file smaller than 40 MB for fast network transfer."
            )
            return

        file_name = os.path.basename(file_path)
        self.pending_file = {
            "path": file_path,
            "name": file_name,
            "size": file_size
        }

        icon = get_file_icon(file_name)
        size_str = format_file_size(file_size)
        self.file_preview_lbl.configure(text=f"{icon}  Attached: {file_name}  ({size_str})")
        self.file_preview_frame.pack(fill="x", padx=10, pady=(0, 6), before=self.input_row)
        self.msg_entry.configure(placeholder_text="Add an optional caption, then click Send ➤...")
        self.msg_entry.focus()

    def _cancel_attached_file(self):
        """Remove pending file attachment and hide preview chip."""
        self.pending_file = None
        if hasattr(self, "file_preview_frame") and self.file_preview_frame:
            self.file_preview_frame.pack_forget()
        if hasattr(self, "msg_entry") and self.msg_entry:
            if self.active_chat == "group":
                self.msg_entry.configure(placeholder_text="Message # General (Group)...")
            else:
                self.msg_entry.configure(placeholder_text=f"Message {self.active_chat} privately...")

    def _on_return_pressed(self, event=None):
        """Prevent event bubbling and call _send_message once cleanly."""
        self._send_message()
        return "break"

    # =========================================================================
    # Conversation Switching (Group vs 1-to-1 DMs with Friends)
    # =========================================================================
    def _select_conversation(self, target: str):
        """Switch active conversation to 'group' or a specific friend."""
        self.active_chat = target
        # Clear unread counter for this conversation
        self.unread_counts[target] = 0
        self._cancel_attached_file()

        # Update UI Header & Input Placeholder
        if target == "group":
            self.group_chat_btn.configure(fg_color=COLOR_SIDEBAR_ACTIVE)
            self.chat_title_lbl.configure(text="👥 Group Chat (# General)")
            self.chat_subtitle_lbl.configure(text="Messages are visible to all connected members")
            self.msg_entry.configure(placeholder_text="Message # General (Group)...")
        else:
            self.group_chat_btn.configure(fg_color="transparent")
            self.chat_title_lbl.configure(text=f"🔒 Direct Message: {target}")
            self.chat_subtitle_lbl.configure(text=f"Private 1-to-1 conversation with {target}")
            self.msg_entry.configure(placeholder_text=f"Message {target} privately...")

        self._render_friends_list()
        self._load_active_chat_history()

    def _load_active_chat_history(self):
        """Fetch message history from SQLite3 database and render in chat scroll frame."""
        for child in self.chat_scroll.winfo_children():
            child.destroy()

        if not self.current_user:
            return

        # Load from SQLite3 database scoped to self.current_user
        messages = database.get_chat_history(self.current_user, self.active_chat, limit=250)

        if not messages:
            if self.active_chat == "group":
                self._add_system_message("This is the beginning of the # General group chat.")
            else:
                self._add_system_message(f"This is the beginning of your direct message history with {self.active_chat}.")
        else:
            for m in messages:
                mid = m.get("msg_id")
                if mid:
                    self.seen_msg_ids.add(mid)

                is_sent = (m["sender"].strip().lower() == self.current_user.strip().lower())
                m_type = m.get("msg_type", "text")
                if m_type == "file":
                    self._render_file_bubble(
                        sender="You" if is_sent else m["sender"],
                        text=m["text"],
                        timestamp=m["timestamp"],
                        is_sent=is_sent,
                        file_name=m.get("file_name", "file"),
                        file_size=m.get("file_size", 0),
                        file_path=m.get("file_path", "")
                    )
                else:
                    self._render_bubble(
                        sender="You" if is_sent else m["sender"],
                        text=m["text"],
                        timestamp=m["timestamp"],
                        is_sent=is_sent
                    )

    def _render_friends_list(self):
        """Update the Direct Messages sidebar list with all online friends and past contacts."""
        for child in self.friends_scroll.winfo_children():
            child.destroy()

        my_name = (self.current_user or "").strip().lower()

        # 1. Connected online members
        online_set = {u.strip().lower() for u in self.online_users if u.strip().lower() != my_name}

        # 2. Past chat contacts stored in database
        db_contacts = database.get_recent_contacts(self.current_user) if self.current_user else []

        # Merge contacts maintaining order: online first, then offline
        all_friends = []
        seen = set()

        # Online friends
        for u in self.online_users:
            uname = u.strip()
            if uname.lower() != my_name and uname.lower() not in seen:
                seen.add(uname.lower())
                all_friends.append((uname, True))

        # Offline past contacts from database
        for u in db_contacts:
            uname = u.strip()
            if uname.lower() != my_name and uname.lower() not in seen:
                seen.add(uname.lower())
                all_friends.append((uname, False))

        self.friends_count_lbl.configure(text=f"DIRECT MESSAGES ({len(all_friends)})")

        # Update Group chat button badge
        group_unread = self.unread_counts.get("group", 0)
        group_text = "👥 # General (Group)"
        if group_unread > 0:
            group_text += f" ({group_unread})"
        self.group_chat_btn.configure(text=group_text)

        if not all_friends:
            empty_lbl = ctk.CTkLabel(
                self.friends_scroll,
                text="No contacts yet.\nJoin a group to chat with friends!",
                font=ctk.CTkFont(size=11, slant="italic"),
                text_color=COLOR_TEXT_MUTED,
                justify="center"
            )
            empty_lbl.pack(pady=12)
            return

        for friend, is_online in all_friends:
            is_active = (self.active_chat.lower() == friend.lower())
            unread = self.unread_counts.get(friend, 0)

            btn_color = COLOR_SIDEBAR_ACTIVE if is_active else "transparent"
            hover_col = "#1d4ed8" if is_active else "#1e293b"

            display_name = friend
            if is_online and friend == self.room_host:
                display_name += " 👑"
            elif not is_online:
                display_name += " (Offline)"

            if unread > 0:
                display_name += f" ({unread})"

            dot_icon = "🟢" if is_online else "⚪"

            btn = ctk.CTkButton(
                self.friends_scroll,
                text=f"{dot_icon} {display_name}",
                anchor="w",
                command=lambda f=friend: self._select_conversation(f),
                height=32,
                corner_radius=6,
                fg_color=btn_color,
                hover_color=hover_col,
                font=ctk.CTkFont(size=11, weight="bold" if is_active or unread > 0 else "normal"),
                text_color="#ffffff" if is_active else ("#e2e8f0" if is_online else "#94a3b8")
            )
            btn.pack(fill="x", pady=2, padx=2)

    # =========================================================================
    # Connection & Tunneling Handlers
    # =========================================================================
    def _on_target_changed(self, *args):
        """Auto-parse port if full URL/port string is typed or pasted."""
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
                self._add_system_message(f"🔗 Pinggy link saved: {extracted}. Click 'Copy Link for Friends' to share!")
        except Exception as e:
            messagebox.showinfo("Clipboard", f"Could not read clipboard: {e}")

    def _copy_public_pinggy_url(self):
        """Copy the Host Pinggy public URL to clipboard for sending to members."""
        url = self.public_pinggy_url.get().strip()
        if not url:
            messagebox.showwarning(
                "No Public Link Found",
                "Please enter or launch Pinggy to get your public URL first!"
            )
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._add_system_message(f"📋 Copied Pinggy link to clipboard: {url}\nSend this link to friends so they can join!")

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
                self._add_system_message("🚀 Pinggy tunnel launched! When you enter password in CMD, the link will auto-fetch!")
            else:
                messagebox.showerror("Tunnel Error", msg)

    def _update_mode_ui(self):
        """Update labels, default values, and assistant panels based on selected role."""
        if not hasattr(self, "ip_lbl") or not self.ip_lbl:
            return

        if self.network.is_connected or self.network.is_listening:
            return

        if "Host" in self.mode.get():
            self.ip_lbl.configure(text="Bind IP:")
            self.host_ip.set("127.0.0.1")
            self.port.set("5001")
            self.action_btn.configure(text="Start Group", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

            self.client_assistant_box.pack_forget()
            self.host_assistant_box.pack(fill="x", padx=8, pady=6)
            self._update_tunnel_label()
        else:
            self.ip_lbl.configure(text="Target Host:")
            self.host_ip.set("a.pinggy.io")
            self.port.set("5001")
            self.action_btn.configure(text="Join Group", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

            self.host_assistant_box.pack_forget()
            self.client_assistant_box.pack(fill="x", padx=8, pady=6)

    def _update_tunnel_label(self):
        try:
            port = int(self.port.get().strip() or "5001")
        except ValueError:
            port = 5001
        self.tunnel_cmd_lbl.configure(text=get_pinggy_command(port))

    def _poll_auto_fetch_pinggy_url(self):
        """Check if Pinggy public URL has become active via API (after password in CMD) or clipboard."""
        try:
            if hasattr(self, "mode") and "Host" in self.mode.get():
                current_val = self.public_pinggy_url.get().strip()

                # 1. Check local debugger API
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

                # 2. Check clipboard
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
                                    self._add_system_message(f"🎉 Pinggy URL auto-filled from clipboard:\n{url}")
                    except Exception:
                        pass
        except Exception:
            pass

        self.root.after(1200, self._poll_auto_fetch_pinggy_url)

    def _set_status(self, text: str, color: str):
        self.status_text.set(text)
        if hasattr(self, "status_dot") and self.status_dot:
            self.status_dot.configure(text_color=color)

    def _toggle_connection(self):
        """Start or stop hosting/connecting."""
        if self.network.is_connected or self.network.is_listening:
            self.network.disconnect()
            self._set_status("Offline - Left Group", COLOR_RED)
            self._on_disconnected_ui()
            self._add_system_message("You left / stopped the chat room.")
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

        my_name = self.current_user or "User"

        if "Host" in self.mode.get():
            success, msg = self.network.start_host(host, port, username=my_name)
            if success:
                self._set_status(f"Group Active ({host}:{port})", COLOR_GREEN)
                self.action_btn.configure(text="Stop Group", fg_color=COLOR_RED, hover_color="#dc2626")
                self._disable_inputs()
                self.msg_entry.configure(state="normal")
                self.send_btn.configure(state="normal")
                if hasattr(self, "attach_btn") and self.attach_btn:
                    self.attach_btn.configure(state="normal")
                self.msg_entry.focus()
                self._add_system_message(f"👑 Room started by {my_name}! Ready for friends to join.")
            else:
                messagebox.showerror("Host Error", f"Could not start group server: {msg}")
        else:
            self._set_status(f"Joining {host}:{port}...", COLOR_YELLOW)
            self.action_btn.configure(text="Cancel", fg_color=COLOR_RED, hover_color="#dc2626")
            self._disable_inputs()
            self.network.connect_to_peer(host, port, username=my_name)

    def _disable_inputs(self):
        self.mode_btn.configure(state="disabled")
        self.ip_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")

    def _enable_inputs(self):
        self.mode_btn.configure(state="normal")
        self.ip_entry.configure(state="normal")
        self.port_entry.configure(state="normal")

    def _on_connected_ui(self, peer_addr):
        self._set_status("In Group Chat", COLOR_GREEN)
        self.action_btn.configure(text="Leave Group", fg_color=COLOR_RED, hover_color="#dc2626")
        self.msg_entry.configure(state="normal")
        self.send_btn.configure(state="normal")
        if hasattr(self, "attach_btn") and self.attach_btn:
            self.attach_btn.configure(state="normal")
        self.msg_entry.focus()
        self._add_system_message("🎉 Connected to the room! You can chat in Group or pick a friend for 1-to-1.")

    def _on_disconnected_ui(self):
        self._enable_inputs()
        self._update_mode_ui()
        self.msg_entry.delete(0, "end")
        self.msg_entry.configure(state="disabled", placeholder_text="Start or join a group to start messaging...")
        self.send_btn.configure(state="disabled")
        if hasattr(self, "attach_btn") and self.attach_btn:
            self.attach_btn.configure(state="disabled")
        self._cancel_attached_file()
        self.online_users = []
        self._render_friends_list()

    # =========================================================================
    # Messaging (Sending & Displaying)
    # =========================================================================
    def _send_message(self):
        if self._is_sending:
            return
        self._is_sending = True
        try:
            text = self.msg_entry.get().strip()
            pending = self.pending_file

            if not text and not pending:
                return

            if not (self.network.is_connected or self.network.is_listening):
                return

            timestamp = datetime.now().strftime("%I:%M %p")
            sender = self.current_user or "Me"
            recipient = self.active_chat  # 'group' or friend's username
            msg_id = uuid.uuid4().hex

            if pending:
                # Send file attachment (with optional caption)
                self._cancel_attached_file()
                self.msg_entry.delete(0, "end")
                self._send_file_message(pending, text, sender, recipient, timestamp, msg_id)
            else:
                # Regular text chat
                payload = {
                    "type": "chat",
                    "msg_id": msg_id,
                    "sender": sender,
                    "recipient": recipient,
                    "text": text,
                    "timestamp": timestamp
                }

                # Register locally generated msg_id so this client never processes it as duplicate
                self.seen_msg_ids.add(msg_id)

                # 1. Send over socket network
                if self.network.send_message(payload):
                    # 2. Save to SQLite3 database scoped to sender (self.current_user)!
                    database.save_message(
                        owner_user=sender,
                        sender=sender,
                        recipient=recipient,
                        text=text,
                        timestamp=timestamp,
                        msg_id=msg_id,
                        msg_type="text"
                    )

                    # 3. Render immediately on screen
                    self._render_bubble(sender="You", text=text, timestamp=timestamp, is_sent=True)
                    self.msg_entry.delete(0, "end")
                else:
                    messagebox.showwarning("Send Failed", "Message could not be delivered.")
        finally:
            self._is_sending = False

    def _send_file_message(self, file_info: dict, caption: str, sender: str, recipient: str, timestamp: str, msg_id: str):
        """Prepare, encode, save locally, and transmit file in background thread."""
        file_path = file_info["path"]
        file_name = file_info["name"]
        file_size = file_info["size"]

        # 1. Register msg_id
        self.seen_msg_ids.add(msg_id)

        # 2. Save to database scoped to sender (pointing to sender's original file)
        database.save_message(
            owner_user=sender,
            sender=sender,
            recipient=recipient,
            text=caption,
            timestamp=timestamp,
            msg_id=msg_id,
            msg_type="file",
            file_name=file_name,
            file_size=file_size,
            file_path=file_path
        )

        # 3. Render file bubble immediately on sender's feed
        self._render_file_bubble(
            sender="You",
            text=caption,
            timestamp=timestamp,
            is_sent=True,
            file_name=file_name,
            file_size=file_size,
            file_path=file_path
        )

        # 4. Transmit over socket in background worker thread so GUI stays fluid
        def _worker():
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                b64_str = base64.b64encode(file_bytes).decode("ascii")

                payload = {
                    "type": "file",
                    "msg_id": msg_id,
                    "sender": sender,
                    "recipient": recipient,
                    "text": caption,
                    "filename": file_name,
                    "file_size": file_size,
                    "file_bytes_b64": b64_str,
                    "timestamp": timestamp
                }
                ok = self.network.send_message(payload)
                if not ok:
                    self.event_queue.put(("error", f"Failed to deliver file '{file_name}'."))
            except Exception as e:
                self.event_queue.put(("error", f"File sending error: {e}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _render_file_bubble(self, sender: str, text: str, timestamp: str, is_sent: bool, file_name: str, file_size: int, file_path: str):
        """Render modern file attachment card in active chat feed."""
        bubble_row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        bubble_row.pack(fill="x", pady=5, padx=6)

        bubble_color = COLOR_SENT if is_sent else COLOR_RECV
        align = "e" if is_sent else "w"

        bubble = ctk.CTkFrame(bubble_row, fg_color=bubble_color, corner_radius=14)
        bubble.pack(side="right" if is_sent else "left", anchor=align, padx=4)

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

        # Optional Caption Text
        if text:
            caption_lbl = ctk.CTkLabel(
                bubble,
                text=text,
                font=ctk.CTkFont(size=13),
                text_color="#ffffff" if is_sent else "#f1f5f9",
                wraplength=480,
                justify="right" if is_sent else "left"
            )
            caption_lbl.pack(anchor=align, padx=14, pady=(2, 6))

        # Inner File Card Box
        card_bg = "#0f172a" if is_sent else "#1e293b"
        file_card = ctk.CTkFrame(bubble, fg_color=card_bg, corner_radius=10)
        file_card.pack(anchor=align, padx=12, pady=(2, 10))

        card_inner = ctk.CTkFrame(file_card, fg_color="transparent")
        card_inner.pack(fill="x", padx=12, pady=8)

        # File Icon
        icon_lbl = ctk.CTkLabel(card_inner, text=get_file_icon(file_name), font=ctk.CTkFont(size=26))
        icon_lbl.pack(side="left", padx=(0, 10))

        # File Details
        info_col = ctk.CTkFrame(card_inner, fg_color="transparent")
        info_col.pack(side="left", fill="x", expand=True)

        display_name = file_name
        if len(display_name) > 30:
            b, ext = os.path.splitext(display_name)
            display_name = b[:24] + "..." + ext

        fname_lbl = ctk.CTkLabel(
            info_col,
            text=display_name,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff"
        )
        fname_lbl.pack(anchor="w")

        fsize_lbl = ctk.CTkLabel(
            info_col,
            text=format_file_size(file_size),
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        fsize_lbl.pack(anchor="w")

        # Action Buttons
        btn_row = ctk.CTkFrame(file_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))

        open_btn = ctk.CTkButton(
            btn_row,
            text="📂 Open",
            width=70,
            height=28,
            corner_radius=6,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda p=file_path: self._open_file(p)
        )
        open_btn.pack(side="left", padx=(0, 6))

        save_btn = ctk.CTkButton(
            btn_row,
            text="💾 Save As...",
            width=85,
            height=28,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda p=file_path, n=file_name: self._save_file_as(p, n)
        )
        save_btn.pack(side="left")

        # Auto-scroll to bottom
        self.root.update_idletasks()
        try:
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _open_file(self, file_path: str):
        """Open the file with default system application or reveal in folder."""
        target = file_path
        if not target or not os.path.exists(target):
            if target:
                fallback = os.path.join(DOWNLOADS_DIR, os.path.basename(target))
                if os.path.exists(fallback):
                    target = fallback
                else:
                    messagebox.showinfo("File Not Found", "The file was not found on this computer.")
                    return
            else:
                messagebox.showinfo("File Not Found", "The file was not found on this computer.")
                return

        try:
            os.startfile(target)
        except Exception:
            try:
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            except Exception as e:
                messagebox.showerror("Open Error", f"Could not open file: {e}")

    def _save_file_as(self, file_path: str, default_name: str):
        """Prompt user to save a copy of the file anywhere on their computer."""
        target = file_path
        if not target or not os.path.exists(target):
            if target:
                fallback = os.path.join(DOWNLOADS_DIR, os.path.basename(target))
                if os.path.exists(fallback):
                    target = fallback
                else:
                    messagebox.showinfo("File Not Found", "The original file is not available to copy.")
                    return
            else:
                messagebox.showinfo("File Not Found", "The original file is not available to copy.")
                return

        ext = os.path.splitext(default_name)[1]
        save_target = filedialog.asksaveasfilename(
            title="Save File As",
            initialfile=default_name,
            defaultextension=ext
        )
        if save_target:
            try:
                shutil.copy2(target, save_target)
                messagebox.showinfo("Saved Successfully", f"File saved to:\n{save_target}")
            except Exception as e:
                messagebox.showerror("Save Failed", f"Could not save file: {e}")

    def _render_bubble(self, sender: str, text: str, timestamp: str, is_sent: bool):
        """Render modern message card in active chat feed."""
        bubble_row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        bubble_row.pack(fill="x", pady=4, padx=6)

        bubble_color = COLOR_SENT if is_sent else COLOR_RECV
        align = "e" if is_sent else "w"

        bubble = ctk.CTkFrame(bubble_row, fg_color=bubble_color, corner_radius=14)
        bubble.pack(side="right" if is_sent else "left", anchor=align, padx=4)

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

        body_lbl = ctk.CTkLabel(
            bubble,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color="#ffffff" if is_sent else "#f1f5f9",
            wraplength=480,
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

    # =========================================================================
    # Thread Callbacks (Push to thread-safe queue)
    # =========================================================================
    def _on_net_connected(self, peer_addr):
        self.event_queue.put(("connected", peer_addr))

    def _on_net_message(self, message):
        self.event_queue.put(("message", message))

    def _on_net_user_list_changed(self, user_list, host_username):
        self.event_queue.put(("user_list", (user_list, host_username)))

    def _on_net_system_notice(self, notice):
        self.event_queue.put(("notice", notice))

    def _on_net_disconnected(self):
        self.event_queue.put(("disconnected", None))

    def _on_net_error(self, err_msg):
        self.event_queue.put(("error", err_msg))

    def _process_network_queue(self):
        """Safely process messages from network threads on Tkinter main thread."""
        while not self.event_queue.empty():
            try:
                event_type, data = self.event_queue.get_nowait()
                if event_type == "connected":
                    self._on_connected_ui(data)

                elif event_type == "message":
                    if isinstance(data, dict):
                        m_type = data.get("type")
                        if m_type == "chat":
                            sender = data.get("sender", "Peer")
                            recipient = data.get("recipient", "group")
                            text = data.get("text", "")
                            timestamp = data.get("timestamp", datetime.now().strftime("%I:%M %p"))
                            msg_id = data.get("msg_id") or f"{sender}_{recipient}_{text}_{timestamp}"

                            # Skip if this message was already received or processed (deduplication)
                            if msg_id in self.seen_msg_ids:
                                continue
                            self.seen_msg_ids.add(msg_id)

                            # Save to SQLite3 database scoped to this receiver (self.current_user)
                            database.save_message(
                                owner_user=self.current_user or "",
                                sender=sender,
                                recipient=recipient,
                                text=text,
                                timestamp=timestamp,
                                msg_id=msg_id,
                                msg_type="text"
                            )

                            # Determine which chat this message belongs to
                            is_for_active_chat = False
                            if recipient == "group" and self.active_chat == "group":
                                is_for_active_chat = True
                            elif recipient != "group":
                                # 1-to-1 message: check if we are currently viewing this friend's DM
                                if self.active_chat.lower() == sender.lower():
                                    is_for_active_chat = True

                            if is_for_active_chat:
                                self._render_bubble(sender=sender, text=text, timestamp=timestamp, is_sent=False)
                            else:
                                # Increment unread counter and update sidebar
                                key = "group" if recipient == "group" else sender
                                self.unread_counts[key] = self.unread_counts.get(key, 0) + 1
                                self._render_friends_list()

                        elif m_type == "file":
                            sender = data.get("sender", "Peer")
                            recipient = data.get("recipient", "group")
                            text = data.get("text", "")
                            filename = data.get("filename", "received_file")
                            file_size = data.get("file_size", 0)
                            b64_str = data.get("file_bytes_b64", "")
                            timestamp = data.get("timestamp", datetime.now().strftime("%I:%M %p"))
                            msg_id = data.get("msg_id") or f"{sender}_{recipient}_{text}_{filename}_{timestamp}"

                            if msg_id in self.seen_msg_ids:
                                continue
                            self.seen_msg_ids.add(msg_id)

                            # Decode incoming file bytes
                            try:
                                file_bytes = base64.b64decode(b64_str)
                            except Exception:
                                file_bytes = b""

                            safe_name = os.path.basename(filename) or "received_file"
                            dest_path = os.path.join(DOWNLOADS_DIR, safe_name)

                            # If a file with the same name exists, check if it has identical content
                            is_identical = False
                            if os.path.exists(dest_path):
                                try:
                                    if os.path.getsize(dest_path) == len(file_bytes):
                                        with open(dest_path, "rb") as ef:
                                            existing_hash = hashlib.md5(ef.read()).hexdigest()
                                        if existing_hash == hashlib.md5(file_bytes).hexdigest():
                                            is_identical = True
                                except Exception:
                                    is_identical = False

                                if not is_identical:
                                    base, ext = os.path.splitext(safe_name)
                                    counter = 1
                                    while os.path.exists(dest_path):
                                        dest_path = os.path.join(DOWNLOADS_DIR, f"{base} ({counter}){ext}")
                                        counter += 1

                            try:
                                if not is_identical:
                                    with open(dest_path, "wb") as f:
                                        f.write(file_bytes)
                            except Exception as e:
                                print(f"Error saving received file: {e}")
                                dest_path = ""

                            # Save to SQLite database scoped to receiver
                            database.save_message(
                                owner_user=self.current_user or "",
                                sender=sender,
                                recipient=recipient,
                                text=text,
                                timestamp=timestamp,
                                msg_id=msg_id,
                                msg_type="file",
                                file_name=safe_name,
                                file_size=file_size,
                                file_path=dest_path
                            )

                            # Determine if belongs to active chat
                            is_for_active_chat = False
                            if recipient == "group" and self.active_chat == "group":
                                is_for_active_chat = True
                            elif recipient != "group":
                                if self.active_chat.lower() == sender.lower():
                                    is_for_active_chat = True

                            if is_for_active_chat:
                                self._render_file_bubble(
                                    sender=sender,
                                    text=text,
                                    timestamp=timestamp,
                                    is_sent=False,
                                    file_name=safe_name,
                                    file_size=file_size,
                                    file_path=dest_path
                                )
                            else:
                                key = "group" if recipient == "group" else sender
                                self.unread_counts[key] = self.unread_counts.get(key, 0) + 1
                                self._render_friends_list()

                elif event_type == "user_list":
                    users, host_user = data
                    self.online_users = users
                    self.room_host = host_user
                    if self.main_container:
                        self._render_friends_list()

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

        self.root.after(50, self._process_network_queue)

    def _on_close(self):
        """Clean shutdown of sockets and tunnel processes."""
        self.network.disconnect()
        self.tunnel_manager.stop_tunnel()
        self.root.destroy()
