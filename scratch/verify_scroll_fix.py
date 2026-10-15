import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database
import customtkinter as ctk
from gui import SocialLiteGUI

def test_scroll_issue_fix():
    print("=== Testing Scroll Fix for Switching Between Long & Short Chats ===")
    test_db = os.path.join(tempfile.gettempdir(), f"test_scroll_{int(time.time())}.db")
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_db()

    database.register_user("alice", "pass")
    database.register_user("user_a", "pass")
    database.register_user("user_b", "pass")

    # 1. User A has 60 messages (very tall chat)
    for i in range(60):
        database.save_message("alice", "user_a", "alice", f"User A message {i}", msg_id=f"a_{i}")

    # 2. User B has only 1 message (short chat)
    database.save_message("alice", "user_b", "alice", "Single message from User B", msg_id="b_1")

    root = ctk.CTk()
    root.geometry("800x600+-2000+-2000")
    app = SocialLiteGUI(root)
    app.current_user = "alice"
    app._show_main_dashboard()
    root.update()

    # Step 1: Switch to User A (60 messages)
    print("Selecting User A (60 messages)...")
    app._select_conversation("user_a")
    root.update()

    yview_a = app.chat_scroll._parent_canvas.yview()
    print(f"User A yview: {yview_a}")
    # With 60 messages, content overflows the 600px window, so y2 == 1.0 and y1 > 0.0 (scrolled to bottom)
    assert yview_a[1] == 1.0, f"User A should be scrolled to bottom (1.0), got {yview_a}"
    assert yview_a[0] > 0.0, f"User A should overflow viewport, got {yview_a}"
    print("PASS: User A (many messages) scrolled to bottom correctly.")

    # Step 2: Switch to User B (1 message)
    print("Selecting User B (1 message)...")
    app._select_conversation("user_b")
    root.update()

    yview_b = app.chat_scroll._parent_canvas.yview()
    print(f"User B yview: {yview_b}")
    # User B has only 1 message, so content fits completely on screen. It must be (0.0, 1.0)!
    assert yview_b == (0.0, 1.0), f"User B with 1 message MUST be at (0.0, 1.0), got {yview_b}"
    print("PASS: User B (single message) is positioned at the top and completely visible!")

    # Step 3: Switch back to User A
    print("Selecting User A again...")
    app._select_conversation("user_a")
    root.update()
    yview_a2 = app.chat_scroll._parent_canvas.yview()
    assert yview_a2[1] == 1.0 and yview_a2[0] > 0.0
    print("PASS: User A reloaded at bottom correctly.")

    # Step 4: Switch back to User B
    print("Selecting User B again...")
    app._select_conversation("user_b")
    root.update()
    yview_b2 = app.chat_scroll._parent_canvas.yview()
    assert yview_b2 == (0.0, 1.0), f"User B MUST stay at (0.0, 1.0), got {yview_b2}"
    print("PASS: User B reloaded at top with message 100% visible!")

    root.destroy()
    database.DB_FILE = orig_db
    try:
        os.remove(test_db)
    except Exception:
        pass

    print("\nALL SCROLL TESTS PASSED PERFECTLY! 🎉")

if __name__ == "__main__":
    test_scroll_issue_fix()
