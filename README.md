# SocialLite - Multi-User Group & 1-to-1 Messenger

A modern, high-performance desktop messaging application in Python. Supports **Multi-User Group Chat** where multiple users can connect to a group room simultaneously, with native support for global internet communication using Pinggy reverse tunnels (e.g., Host in Assam, multiple Members in Delhi, Mumbai, Kolkata).

---

## ⚡ Instant Auto-Fetch Pinggy Feature

- **Zero-Manual-Copying URL Auto-Fetch**:
  - The Pinggy command includes `-L4300:localhost:4300`:
    ```bash
    ssh -p 443 -L4300:localhost:4300 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R0:127.0.0.1:5001 tcp@a.pinggy.io
    ```
  - When you launch the tunnel and **enter your password in CMD**, SocialLite **automatically fetches the generated `tcp://...` URL** via the local API the instant the connection completes!
  - It **automatically fills the Public Link box** in SocialLite.
  - It **automatically copies the URL to your clipboard** ready to paste to friends!

---

## 👥 Group Messaging Features

- **Multi-Client Group Architecture**:
  - The **Host (Group Admin)** creates the room.
  - Any number of **Members** can join the group room simultaneously.
  - Messages sent by any member are automatically **broadcast to all other members** in real-time.
- **Dedicated Host Pinggy Input Box & UX**:
  - **Launch Tunnel**: One-click launch with automated console.
  - **Auto-Fetched Public Link Box**: A dedicated input box for the Host showing their public Pinggy link (`tcp://...`).
  - **📋 Copy Link for Members**: One-click copy with instant confirmation.
- **Live Members Sidebar**:
  - Displays real-time active users (`👥 Members (3)`).
  - Online presence indicators (`●`).
  - Automatically updates when members join or leave.
- **Distinct Sender Colors**:
  - Each group member gets a unique, pleasant color tag so it's easy to follow group conversations.
- **Join / Leave Announcements**:
  - Centralized notification pills in the feed (`🎉 Bob joined the group!`, `👋 Charlie left the group.`).

---

## 📁 Project Structure

```
c:\python_software\social_lite\
├── network.py       # Multi-client TCP socket server, broadcast & presence tracking
├── tunnel.py        # Pinggy tunnel runner, debugger API client (4300) & parser
├── gui.py           # Modern CustomTkinter GUI with auto-fetch & Members sidebar
├── main.py          # Application entry point
└── README.md        # Documentation
```

---

## 🚀 How to Run

Launch the application:
```powershell
cd c:\python_software\social_lite
python main.py
```

---

## 🌐 Assam to Delhi (Global Group Workflow)

### 1. Host (Assam)
1. Set Role: **Host (Group Admin)** (Port `5001`).
2. Click **Start Group**.
3. Click **🚀 Launch Tunnel** (or run the command shown in the purple panel).
4. Enter your password in CMD when prompted.
5. **Boom!** The app **automatically fetches the URL** into the **Public Link for Members** box and copies it to your clipboard.
6. Send the link to your friends!

### 2. Members (Delhi, Mumbai, etc.)
1. Set Role: **Connect (Join Group)**.
2. In **Target Host**, click **📋 Paste from Clipboard** (or paste the `tcp://...` address).
3. Click **Join Group**!
