import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database

def test_physical_file_deletion():
    print("=== Testing Physical File Deletion on 'Delete for Everyone' ===")
    test_db = os.path.join(tempfile.gettempdir(), f"test_file_del_{int(time.time())}.db")
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_db()

    # Create dummy receiver downloads dir
    test_downloads = os.path.join(tempfile.gettempdir(), f"test_downloads_{int(time.time())}")
    os.makedirs(test_downloads, exist_ok=True)
    orig_downloads = database.DOWNLOADS_DIR
    database.DOWNLOADS_DIR = test_downloads

    # 1. Simulate sender's original file outside downloads (e.g. on Desktop)
    sender_outside_dir = os.path.join(tempfile.gettempdir(), f"test_desktop_{int(time.time())}")
    os.makedirs(sender_outside_dir, exist_ok=True)
    sender_file = os.path.join(sender_outside_dir, "my_original.pdf")
    with open(sender_file, "wb") as f:
        f.write(b"Sender original content")

    # 2. Simulate receiver's downloaded file inside downloads/
    receiver_file = os.path.join(test_downloads, "received_doc.pdf")
    with open(receiver_file, "wb") as f:
        f.write(b"Receiver downloaded content")

    msg_id = "msg_file_999"

    # Save sender record (pointing to Desktop)
    database.save_message(
        owner_user="alice",
        sender="alice",
        recipient="bob",
        text="Here is the doc",
        timestamp="10:00 AM",
        msg_id=msg_id,
        msg_type="file",
        file_name="received_doc.pdf",
        file_size=100,
        file_path=sender_file
    )

    # Save receiver record (pointing to downloads/)
    database.save_message(
        owner_user="bob",
        sender="alice",
        recipient="bob",
        text="Here is the doc",
        timestamp="10:00 AM",
        msg_id=msg_id,
        msg_type="file",
        file_name="received_doc.pdf",
        file_size=100,
        file_path=receiver_file
    )

    assert os.path.exists(receiver_file), "Receiver file should exist before delete"
    assert os.path.exists(sender_file), "Sender file should exist before delete"

    # 3. Trigger Delete for Everyone on receiver's end
    print("Triggering delete_message_for_everyone...")
    database.delete_message_for_everyone(msg_id, delete_physical_file=True)

    # 4. Verify receiver physical file is GONE
    assert not os.path.exists(receiver_file), "Receiver physical file in downloads/ should be DELETED!"
    print("PASS: Receiver physical file in downloads/ was successfully deleted!")

    # 5. Verify sender's file outside downloads is SAFE
    assert os.path.exists(sender_file), "Sender's original file outside downloads/ must NOT be deleted!"
    print("PASS: Sender original file outside downloads was protected!")

    # 6. Verify database records are deleted
    alice_hist = database.get_chat_history("alice", "bob")
    bob_hist = database.get_chat_history("bob", "alice")
    assert len(alice_hist) == 0
    assert len(bob_hist) == 0
    print("PASS: Database records for both users deleted cleanly.")

    # Cleanup test files
    try:
        os.remove(sender_file)
        os.rmdir(sender_outside_dir)
        os.rmdir(test_downloads)
        os.remove(test_db)
    except Exception:
        pass
    database.DB_FILE = orig_db
    database.DOWNLOADS_DIR = orig_downloads

    print("\nALL PHYSICAL FILE DELETION TESTS PASSED! 🎉")

if __name__ == "__main__":
    test_physical_file_deletion()
