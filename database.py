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
import sys
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime

# Determine base directory: works for both Python script and PyInstaller .exe
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(APP_DIR, "social_lite.db")
DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")


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

    # 2. Messages table for Group and 1-to-1 chats (with file sharing and deduplication constraints)
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
        msg_type TEXT NOT NULL DEFAULT 'text',
        file_name TEXT DEFAULT '',
        file_size INTEGER DEFAULT 0,
        file_path TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'sent',
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
    if "msg_type" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'text';")
    if "file_name" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN file_name TEXT DEFAULT '';")
    if "file_size" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN file_size INTEGER DEFAULT 0;")
    if "file_path" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN file_path TEXT DEFAULT '';")
    if "status" not in existing_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'sent';")

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


def save_message(owner_user: str, sender: str, recipient: str, text: str,
                 timestamp: str = None, msg_id: str = None,
                 msg_type: str = "text", file_name: str = "",
                 file_size: int = 0, file_path: str = "",
                 status: str = "sent") -> int:
    """
    Save a chat or file message to the database, scoped to owner_user and deduplicated by msg_id.
    Prevents duplicate message insertion.
    """
    if not timestamp:
        timestamp = datetime.now().strftime("%I:%M %p")
    if not msg_id:
        # Generate stable fallback ID if none provided
        msg_id = f"{sender}_{recipient}_{text}_{file_name}_{timestamp}"

    owner = (owner_user or sender).strip()
    chat_id = get_canonical_chat_id(sender, recipient)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Check if this owner already has this msg_id stored
        cursor.execute(
            "SELECT id, status FROM messages WHERE owner_user = ? AND msg_id = ?",
            (owner, msg_id)
        )
        existing = cursor.fetchone()
        if existing:
            # Already saved, skip duplicate insertion
            return existing["id"]

        cursor.execute(
            """
            INSERT INTO messages (msg_id, owner_user, chat_id, sender, recipient, text, timestamp, msg_type, file_name, file_size, file_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, owner, chat_id, sender.strip(), recipient.strip(), text.strip(), timestamp, msg_type, file_name, file_size, file_path, status)
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
            SELECT id, msg_id, sender, recipient, text, timestamp, msg_type, file_name, file_size, file_path, status, created_at
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
                    "timestamp": r["timestamp"],
                    "msg_type": r["msg_type"] if "msg_type" in r.keys() else "text",
                    "file_name": r["file_name"] if "file_name" in r.keys() else "",
                    "file_size": r["file_size"] if "file_size" in r.keys() else 0,
                    "file_path": r["file_path"] if "file_path" in r.keys() else "",
                    "status": r["status"] if "status" in r.keys() and r["status"] else "sent"
                })
        return result
    except Exception as e:
        print(f"[DB Error] Failed to load messages: {e}")
        return []
    finally:
        conn.close()


def update_message_status(msg_id: str, new_status: str, owner_user: str = None) -> bool:
    """Update message status (e.g. 'sent' -> 'delivered' -> 'read').
    Never downgrades a 'read' message back to 'delivered' or 'sent'.
    """
    mid = (msg_id or "").strip()
    if not mid:
        return False

    status_ranks = {"sent": 1, "delivered": 2, "read": 3}
    target_rank = status_ranks.get(new_status, 1)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        if owner_user:
            cursor.execute(
                "SELECT id, status FROM messages WHERE msg_id = ? AND owner_user = ?",
                (mid, owner_user.strip())
            )
        else:
            cursor.execute(
                "SELECT id, status FROM messages WHERE msg_id = ?",
                (mid,)
            )
        rows = cursor.fetchall()
        for r in rows:
            curr_status = r["status"] or "sent"
            curr_rank = status_ranks.get(curr_status, 1)
            if target_rank > curr_rank:
                cursor.execute(
                    "UPDATE messages SET status = ? WHERE id = ?",
                    (new_status, r["id"])
                )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB Error] Failed to update message status: {e}")
        return False
    finally:
        conn.close()


def update_messages_status_bulk(msg_ids: list[str], new_status: str, owner_user: str = None) -> bool:
    """Bulk update multiple message IDs to new_status."""
    if not msg_ids:
        return True
    for mid in msg_ids:
        update_message_status(mid, new_status, owner_user)
    return True


def get_unread_incoming_msg_ids(owner_user: str, sender: str) -> list[str]:
    """Get all message IDs sent by 'sender' to 'owner_user' that are not yet marked as 'read'."""
    owner = (owner_user or "").strip()
    snd = (sender or "").strip()
    if not owner or not snd:
        return []

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT msg_id FROM messages
            WHERE owner_user = ? AND sender = ? AND (status IS NULL OR status != 'read')
            """,
            (owner, snd)
        )
        return [r["msg_id"] for r in cursor.fetchall() if r["msg_id"]]
    except Exception as e:
        print(f"[DB Error] Failed to get unread msg ids: {e}")
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


def delete_message_for_me(owner_user: str, msg_id: str) -> bool:
    """Delete a message from owner_user's view only."""
    owner = (owner_user or "").strip()
    mid = (msg_id or "").strip()
    if not owner or not mid:
        return False

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM messages WHERE owner_user = ? AND msg_id = ?",
            (owner, mid)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DB Error] Failed to delete message for me: {e}")
        return False
    finally:
        conn.close()


def get_message_by_id(msg_id: str) -> dict | None:
    """Fetch details of a single message by msg_id."""
    mid = (msg_id or "").strip()
    if not mid:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM messages WHERE msg_id = ? LIMIT 1", (mid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB Error] Failed to fetch message {msg_id}: {e}")
        return None
    finally:
        conn.close()


def delete_message_for_everyone(msg_id: str, delete_physical_file: bool = True) -> bool:
    """Delete a message globally from all participants across the database.
    If delete_physical_file is True and the message is a file located in the downloads/ folder,
    the physical file is also safely deleted from disk if no other message references it.
    """
    mid = (msg_id or "").strip()
    if not mid:
        return False

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. Fetch file paths for this msg_id before deletion
        cursor.execute(
            "SELECT msg_type, file_path, file_name FROM messages WHERE msg_id = ?",
            (mid,)
        )
        file_rows = cursor.fetchall()

        # 2. Delete database records
        cursor.execute(
            "DELETE FROM messages WHERE msg_id = ?",
            (mid,)
        )
        deleted_count = cursor.rowcount
        conn.commit()

        # 3. Clean up physical file in downloads/ folder if requested
        if delete_physical_file and file_rows:
            downloads_dir = os.path.normcase(os.path.realpath(DOWNLOADS_DIR))
            for row in file_rows:
                fpath = (row["file_path"] or "").strip()
                if fpath and os.path.exists(fpath):
                    fpath_norm = os.path.normcase(os.path.realpath(fpath))
                    # Only delete if it resides inside downloads/ folder (e.g. on receiver's PC)
                    if fpath_norm.startswith(downloads_dir):
                        # Ensure no remaining messages reference this exact file_path
                        cursor.execute(
                            "SELECT COUNT(*) as count FROM messages WHERE file_path = ?",
                            (fpath,)
                        )
                        remaining = cursor.fetchone()["count"]
                        if remaining == 0:
                            try:
                                os.remove(fpath)
                                print(f"[File Cleanup] Physically removed received file: {fpath}")
                            except Exception as fe:
                                print(f"[File Cleanup Error] Could not remove {fpath}: {fe}")

        return deleted_count > 0
    except Exception as e:
        print(f"[DB Error] Failed to delete message for everyone: {e}")
        return False
    finally:
        conn.close()


# Automatically initialize tables on import
init_db()

