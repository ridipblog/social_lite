"""
Database layer for SocialLite using Python's built-in sqlite3.
Zero-installation required (sqlite3 is built directly into Python standard library).
Handles:
- User registration and secure login with salted PBKDF2 hashing
- Persistent chat message storage for both Group Chat and 1-to-1 Direct Messages
- Deduplicated message saving with unique msg_id and owner_user scoping
- Chat history retrieval for seamless switching between friends
"""

import sqlite3
import os
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social_lite.db")


def get_connection():
    """Create and return a thread-safe sqlite3 connection."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables if they do not exist, and migrate columns if needed."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Messages table for Group and 1-to-1 chats (with deduplication constraints)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id TEXT,
        owner_user TEXT NOT NULL DEFAULT '',
        chat_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        recipient TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Check and add columns if upgrading an existing DB
    cursor.execute("PRAGMA table_info(messages);")
    existing_cols = [row["name"] for row in cursor.fetchall()]
    if "msg_id" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN msg_id TEXT;")
    if "owner_user" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN owner_user TEXT NOT NULL DEFAULT '';")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_owner ON messages(owner_user, chat_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_unique ON messages(owner_user, msg_id);")

    conn.commit()
    conn.close()


def _hash_password(password: str, salt_hex: str = None) -> tuple[str, str]:
    """Hash password using PBKDF2-HMAC-SHA256 with cryptographic salt."""
    if salt_hex is None:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)

    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return key.hex(), salt_hex


def register_user(username: str, password: str) -> tuple[bool, str]:
    """
    Register a new user account.
    Returns (True, "Registration successful") or (False, error_message).
    """
    username = username.strip()
    if not username:
        return False, "Username cannot be empty."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if not password:
        return False, "Password cannot be empty."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."

    pwd_hash, salt_hex = _hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, pwd_hash, salt_hex)
        )
        conn.commit()
        return True, "Registration successful! You can now log in."
    except sqlite3.IntegrityError:
        return False, f"Username '{username}' is already taken. Please choose another."
    except Exception as e:
        return False, f"Registration failed: {str(e)}"
    finally:
        conn.close()


def login_user(username: str, password: str) -> tuple[bool, str]:
    """
    Authenticate a user.
    Returns (True, clean_username) or (False, error_message).
    """
    username = username.strip()
    if not username or not password:
        return False, "Please enter both username and password."

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, password_hash, salt FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return False, "User not found. Please register first."

        db_username = row["username"]
        db_hash = row["password_hash"]
        db_salt = row["salt"]

        calc_hash, _ = _hash_password(password, db_salt)
        if hmac.compare_digest(calc_hash, db_hash):
            return True, db_username
        else:
            return False, "Incorrect password. Please try again."
    except Exception as e:
        return False, f"Login error: {str(e)}"
    finally:
        conn.close()


def get_canonical_chat_id(sender: str, recipient: str) -> str:
    """Generate consistent chat ID for 1-to-1 or group chat."""
    if recipient.lower() == "group" or sender.lower() == "group":
        return "group"
    # Sort lexicographically so Alice->Bob and Bob->Alice share the exact same chat_id
    u1, u2 = sorted([sender.strip().lower(), recipient.strip().lower()])
    return f"dm:{u1}:{u2}"


def save_message(owner_user: str, sender: str, recipient: str, text: str, timestamp: str = None, msg_id: str = None) -> int:
    """
    Save a chat message to the database, scoped to owner_user and deduplicated by msg_id.
    Prevents duplicate message insertion.
    """
    if not timestamp:
        timestamp = datetime.now().strftime("%I:%M %p")
    if not msg_id:
        # Generate stable fallback ID if none provided
        msg_id = f"{sender}_{recipient}_{text}_{timestamp}"

    owner = (owner_user or sender).strip()
    chat_id = get_canonical_chat_id(sender, recipient)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Check if this owner already has this msg_id stored
        cursor.execute(
            "SELECT id FROM messages WHERE owner_user = ? AND msg_id = ?",
            (owner, msg_id)
        )
        existing = cursor.fetchone()
        if existing:
            # Already saved, skip duplicate insertion
            return existing["id"]

        cursor.execute(
            """
            INSERT INTO messages (msg_id, owner_user, chat_id, sender, recipient, text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, owner, chat_id, sender.strip(), recipient.strip(), text.strip(), timestamp)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[DB Error] Failed to save message: {e}")
        return -1
    finally:
        conn.close()


def get_chat_history(owner_user: str, user2_or_group: str, limit: int = 250) -> list[dict]:
    """Retrieve chat history for owner_user with user2_or_group."""
    chat_id = get_canonical_chat_id(owner_user, user2_or_group)
    owner = (owner_user or "").strip()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, msg_id, sender, recipient, text, timestamp, created_at
            FROM messages
            WHERE (owner_user = ? OR owner_user = '') AND chat_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (owner, chat_id, limit)
        )
        rows = cursor.fetchall()
        # Deduplicate by msg_id in memory just in case of any legacy rows
        seen = set()
        result = []
        for r in rows:
            mid = r["msg_id"] or f"{r['sender']}_{r['recipient']}_{r['text']}_{r['timestamp']}"
            if mid not in seen:
                seen.add(mid)
                result.append({
                    "id": r["id"],
                    "msg_id": mid,
                    "sender": r["sender"],
                    "recipient": r["recipient"],
                    "text": r["text"],
                    "timestamp": r["timestamp"]
                })
        return result
    except Exception as e:
        print(f"[DB Error] Failed to load messages: {e}")
        return []
    finally:
        conn.close()


def get_recent_contacts(owner_user: str) -> list[str]:
    """Retrieve distinct usernames that owner_user has exchanged 1-to-1 DMs with."""
    owner = (owner_user or "").strip()
    if not owner:
        return []

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT
                CASE
                    WHEN lower(sender) = lower(?) THEN recipient
                    ELSE sender
                END as contact
            FROM messages
            WHERE (owner_user = ? OR owner_user = '') AND chat_id != 'group'
            ORDER BY id DESC
            """,
            (owner, owner)
        )
        rows = cursor.fetchall()
        contacts = []
        seen = set()
        for r in rows:
            name = (r["contact"] or "").strip()
            name_lower = name.lower()
            if name and name_lower != "group" and name_lower != owner.lower() and name_lower not in seen:
                seen.add(name_lower)
                contacts.append(name)
        return contacts
    except Exception as e:
        print(f"[DB Error] Failed to load contacts: {e}")
        return []
    finally:
        conn.close()


# Automatically initialize tables on import
init_db()
