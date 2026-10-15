import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database
from gui import get_tick_display, SocialLiteGUI
from network import NetworkManager
import customtkinter as ctk

def test_ticks():
    print("=== 1. Testing Database Tick Status & Progression ===")
    test_db = os.path.join(tempfile.gettempdir(), f"test_ticks_{int(time.time())}.db")
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_db()

    database.register_user("alice", "pass")
    database.register_user("bob", "pass")

    # Initial send
    msg_id = "tick_msg_001"
    database.save_message("alice", "alice", "bob", "Hello Bob", msg_id=msg_id, status="sent")
    history = database.get_chat_history("alice", "bob")
    assert len(history) == 1
    assert history[0]["status"] == "sent", f"Expected 'sent', got {history[0]['status']}"

    # Verify display helper
    tick_text, tick_color = get_tick_display("sent")
    assert tick_text == "✓" and tick_color == "#f8fafc", f"White tick mismatch: {tick_text}, {tick_color}"
    print("PASS: Sent status displays single White tick '✓'.")

    # Update to delivered
    database.update_message_status(msg_id, "delivered")
    history = database.get_chat_history("alice", "bob")
    assert history[0]["status"] == "delivered", f"Expected 'delivered', got {history[0]['status']}"

    tick_text, tick_color = get_tick_display("delivered")
    assert tick_text == "✓✓" and tick_color == "#10b981", f"Green tick mismatch: {tick_text}, {tick_color}"
    print("PASS: Delivered status displays double Green/Grey tick '✓✓'.")

    # Update to read
    database.update_message_status(msg_id, "read")
    history = database.get_chat_history("alice", "bob")
    assert history[0]["status"] == "read", f"Expected 'read', got {history[0]['status']}"

    tick_text, tick_color = get_tick_display("read")
    assert tick_text == "✓✓" and tick_color == "#38bdf8", f"Blue tick mismatch: {tick_text}, {tick_color}"
    print("PASS: Read status displays double Blue tick '✓✓'.")

    # Verify no downgrade (read cannot be downgraded back to delivered)
    database.update_message_status(msg_id, "delivered")
    history = database.get_chat_history("alice", "bob")
    assert history[0]["status"] == "read", "Status was erroneously downgraded!"
    print("PASS: Status cannot be downgraded from 'read'.")

    # === 2. Testing GUI Live Tick Update ===
    print("\n=== 2. Testing GUI Real-Time Tick Widget Update ===")
    root = ctk.CTk()
    root.withdraw()
    app = SocialLiteGUI(root)
    app.current_user = "alice"
    app.active_chat = "bob"
    app.network.is_connected = True
    app.network.send_message = lambda p: True
    app._show_main_dashboard()
    root.update()

    # Render a sent message
    app._render_bubble(sender="You", text="Hi Bob!", timestamp="10:00 AM", is_sent=True, msg_id="gui_msg_100", status="sent")
    root.update()

    assert "gui_msg_100" in app.message_ticks, "Tick label should be tracked"
    lbl = app.message_ticks["gui_msg_100"]
    assert lbl.cget("text") == "✓", f"Expected '✓', got {lbl.cget('text')}"
    assert lbl.cget("text_color") == "#f8fafc", "Expected white color"

    # Live update to delivered
    app._update_tick_ui("gui_msg_100", "delivered")
    root.update()
    assert lbl.cget("text") == "✓✓"
    assert lbl.cget("text_color") == "#10b981"
    print("PASS: GUI dynamically updated to double Green tick '✓✓'.")

    # Live update to read
    app._update_tick_ui("gui_msg_100", "read")
    root.update()
    assert lbl.cget("text") == "✓✓"
    assert lbl.cget("text_color") == "#38bdf8"
    print("PASS: GUI dynamically updated to double Blue tick '✓✓'.")

    root.destroy()
    database.DB_FILE = orig_db
    try:
        os.remove(test_db)
    except Exception:
        pass

    # === 3. Testing Network Routing for msg_delivered and msg_read ===
    print("\n=== 3. Testing Network Routing for msg_delivered and msg_read ===")
    free_port = 59234
    host_msgs = []
    client_msgs = []

    host_net = NetworkManager(on_message=lambda m: host_msgs.append(m))
    client_net = NetworkManager(on_message=lambda m: client_msgs.append(m))

    host_ok, _ = host_net.start_host("127.0.0.1", free_port, "alice")
    assert host_ok
    time.sleep(0.5)

    client_net.connect_to_peer("127.0.0.1", free_port, "bob")
    st = time.time()
    while not client_net.is_connected and time.time() - st < 3.0:
        time.sleep(0.1)
    assert client_net.is_connected

    # Bob sends msg_delivered to Alice
    client_net.send_message({"type": "msg_delivered", "msg_id": "net_msg_1", "sender": "bob", "recipient": "alice"})
    time.sleep(0.5)
    assert any(m.get("type") == "msg_delivered" and m.get("msg_id") == "net_msg_1" for m in host_msgs), "Host should receive msg_delivered"
    print("PASS: msg_delivered packet successfully routed over network.")

    # Bob sends msg_read to Alice
    client_net.send_message({"type": "msg_read", "msg_id": "net_msg_1", "sender": "bob", "recipient": "alice"})
    time.sleep(0.5)
    assert any(m.get("type") == "msg_read" and m.get("msg_id") == "net_msg_1" for m in host_msgs), "Host should receive msg_read"
    print("PASS: msg_read packet successfully routed over network.")

    client_net.disconnect()
    host_net.disconnect()
    time.sleep(0.5)

    print("\nALL TICK TESTS PASSED SUCCESSFULLY! 🎉")

if __name__ == "__main__":
    test_ticks()
