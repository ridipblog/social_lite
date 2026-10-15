import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database
from gui import SocialLiteGUI

def test_gui_delete():
    print("Testing GUI delete integration...")
    test_db = os.path.join(tempfile.gettempdir(), f"test_gui_del_{int(time.time())}.db")
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_db()

    database.register_user("tester", "password")

    import customtkinter as ctk
    root = ctk.CTk()
    root.withdraw()
    app = SocialLiteGUI(root)

    # Switch to chat view for tester
    app.current_user = "tester"
    app._show_main_dashboard()
    app.network.is_connected = True
    app.network.send_message = lambda payload: True
    root.update()

    # Send a message
    app.active_chat = "group"
    app.msg_entry.insert(0, "Test message to delete")
    app._send_message()
    app.root.update()

    assert len(app.message_widgets) == 1, f"Expected 1 tracked widget, got {len(app.message_widgets)}"
    msg_id = list(app.message_widgets.keys())[0]

    # Test GUI delete for me
    app._delete_for_me(msg_id)
    app.root.update()

    assert len(app.message_widgets) == 0, "Widget should be removed after _delete_for_me"
    history = database.get_chat_history("tester", "group")
    assert len(history) == 0, "Database should have 0 messages after _delete_for_me"

    # Send another message and test delete for everyone
    app.msg_entry.insert(0, "Second message")
    app._send_message()
    app.root.update()

    assert len(app.message_widgets) == 1
    msg_id_2 = list(app.message_widgets.keys())[0]

    app._delete_for_everyone(msg_id_2)
    app.root.update()

    assert len(app.message_widgets) == 0
    history = database.get_chat_history("tester", "group")
    assert len(history) == 0

    app.root.destroy()
    database.DB_FILE = orig_db
    try:
        os.remove(test_db)
    except Exception:
        pass

    print("PASS: GUI Delete for Me and Delete for Everyone work perfectly!")

if __name__ == "__main__":
    test_gui_delete()
