# SocialLite - Multi-User Group & 1-to-1 Messenger (SQLite3 Powered)

A modern, high-performance desktop messaging application in Python. Features built-in **User Registration & Login**, **1-to-1 Private Direct Messaging** between friends, and **Multi-User Group Chat**, backed by a zero-setup **SQLite3** database and global Pinggy SSH tunneling.

---

## ❓ Is SQLite3 Required to be Installed or Setup?

> **NO! Absolutely NO installation or setup is needed!**
> 
> Python comes with `sqlite3` **built directly into its standard library** (`import sqlite3`).
> - No `pip install` required.
> - No database server (like MySQL or PostgreSQL) to install or run.
> - All accounts and messages are automatically created and saved in `social_lite.db` right inside the application directory!

---

## 🌟 Key Features

1. **User Authentication (Registration & Login)**:
   - Secure account creation with PBKDF2-HMAC-SHA256 salted password hashing.
   - Clean login/register tabbed interface.
   - User profile badge with one-click **Logout** button.

2. **1-to-1 Direct Messaging & Group Chat**:
   - **👥 Group Chat (`# General`)**: Broadcast message to all connected members in the room.
   - **💬 1-to-1 Direct Messages**:
     - The left sidebar displays all online friends / members.
     - Click any friend's name to switch to a private, direct conversation with them!
     - Direct messages are routed exclusively to that friend.
     - Unread message counters (e.g. `(1)`) alert you when a friend sends you a private DM while you're in the group chat.

3. **Persistent SQLite3 Message History**:
   - Both Group chats and 1-to-1 conversations are automatically stored in `social_lite.db`.
   - Switching between friends loads your full previous chat history instantly.

4. **Global Internet Connection (Pinggy Reverse Tunnel)**:
   - Connect across different networks and cities (Assam <-> Delhi) with 1 click.
   - **Auto-fetch URL**: Enter your password in CMD, and SocialLite automatically grabs the `tcp://...` address, populates the input box, and copies it to your clipboard.

---

## 📁 Project Structure

```
c:\python_software\social_lite\
├── database.py      # SQLite3 user auth (PBKDF2) & chat history persistence (ZERO INSTALLATION)
├── network.py       # TCP socket server, group broadcast & 1-to-1 private routing
├── tunnel.py        # Pinggy SSH reverse tunnel runner & auto-fetch API client
├── gui.py           # CustomTkinter GUI (Auth screen, Friends sidebar, 1-to-1 & Group chat)
├── main.py          # Application entry point
├── social_lite.db   # Auto-created SQLite3 database file
└── README.md        # Documentation
```

---

## 🚀 How to Run

1. Open PowerShell or Terminal:
   ```powershell
   cd c:\python_software\social_lite
   python main.py
   ```

2. **First Time**: Go to the **Register** tab, enter a username and password, and click **Create Account**.
3. **Log In**: Switch to the **Login** tab and log into your account.
4. **Choose Role**:
   - **Host (Group Admin)**: Click **Start Group** to create a chat room (and launch Pinggy tunnel if across internet).
   - **Connect (Join Group)**: Enter the Host's IP / Pinggy link and click **Join Group**.
5. **Chat**:
   - Stay in **👥 # General** for group messaging.
   - Click any friend's name in the left sidebar under **DIRECT MESSAGES** to chat 1-to-1 privately!
