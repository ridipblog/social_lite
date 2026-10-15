import os
import sys
import time
import socket
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database
from network import NetworkManager

def run_tests():
    print("=== Testing Database Delete Functions ===")
    test_db = os.path.join(tempfile.gettempdir(), f"test_social_{int(time.time())}.db")
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_db()

    # 1. Register users
    database.register_user("alice", "pass123")
    database.register_user("bob", "pass123")

    # 2. Save group chat message for both
    msg_id_1 = "group_msg_001"
    database.save_message("alice", "alice", "group", "Hello everyone!", "10:00 AM", msg_id=msg_id_1)
    database.save_message("bob", "alice", "group", "Hello everyone!", "10:00 AM", msg_id=msg_id_1)

    # 3. Save DM for both
    msg_id_2 = "dm_msg_002"
    database.save_message("alice", "alice", "bob", "Private secret", "10:01 AM", msg_id=msg_id_2)
    database.save_message("bob", "alice", "bob", "Private secret", "10:01 AM", msg_id=msg_id_2)

    # 4. Save file message for both
    msg_id_3 = "file_msg_003"
    database.save_message("alice", "bob", "alice", "Check this doc", "10:02 AM", msg_id=msg_id_3, msg_type="file", file_name="notes.pdf", file_size=1024, file_path="C:/dummy/notes.pdf")
    database.save_message("bob", "bob", "alice", "Check this doc", "10:02 AM", msg_id=msg_id_3, msg_type="file", file_name="notes.pdf", file_size=1024, file_path="C:/dummy/notes.pdf")

    # Verify initial count
    alice_group = database.get_chat_history("alice", "group")
    bob_group = database.get_chat_history("bob", "group")
    assert len(alice_group) == 1, f"Expected 1 group message for alice, got {len(alice_group)}"
    assert len(bob_group) == 1, f"Expected 1 group message for bob, got {len(bob_group)}"

    # Test 'Delete for Me': Bob deletes msg_id_1 for me
    print("Testing 'Delete for Me'...")
    database.delete_message_for_me("bob", msg_id_1)
    alice_group = database.get_chat_history("alice", "group")
    bob_group = database.get_chat_history("bob", "group")
    assert len(bob_group) == 0, "Bob should have 0 messages in group after delete for me"
    assert len(alice_group) == 1, "Alice should still have 1 message in group"
    print("PASS: Delete for Me correctly removed message only for Bob.")

    # Test 'Delete for Everyone': Alice deletes DM msg_id_2 for everyone
    print("Testing 'Delete for Everyone'...")
    alice_dm = database.get_chat_history("alice", "bob")
    bob_dm = database.get_chat_history("bob", "alice")
    assert len(alice_dm) == 2, f"Expected 2 DMs (text + file) for alice, got {len(alice_dm)}"
    assert len(bob_dm) == 2, f"Expected 2 DMs (text + file) for bob, got {len(bob_dm)}"

    database.delete_message_for_everyone(msg_id_2)
    alice_dm = database.get_chat_history("alice", "bob")
    bob_dm = database.get_chat_history("bob", "alice")
    assert len(alice_dm) == 1, f"Alice DM should be 1 after delete for everyone, got {len(alice_dm)}"
    assert len(bob_dm) == 1, f"Bob DM should be 1 after delete for everyone, got {len(bob_dm)}"
    assert alice_dm[0]["msg_id"] == msg_id_3
    assert bob_dm[0]["msg_id"] == msg_id_3
    print("PASS: Delete for Everyone removed message across all users.")

    # Test 'Delete for Everyone' on file message msg_id_3
    print("Testing 'Delete for Everyone' on file attachment...")
    database.delete_message_for_everyone(msg_id_3)
    alice_dm_file = database.get_chat_history("alice", "bob")
    bob_dm_file = database.get_chat_history("bob", "alice")
    assert len(alice_dm_file) == 0
    assert len(bob_dm_file) == 0
    print("PASS: Delete for Everyone worked on file message.")

    # Restore DB_FILE
    database.DB_FILE = orig_db
    try:
        os.remove(test_db)
    except Exception:
        pass

    # === Testing Network Broadcasting of delete_message ===
    print("\n=== Testing Network delete_message Routing ===")
    free_port = 59123
    host_received = []
    client_received = []

    host_net = NetworkManager(
        on_message=lambda msg: host_received.append(msg),
        on_connected=lambda addr: None,
        on_disconnected=lambda: None
    )

    client_net = NetworkManager(
        on_message=lambda msg: client_received.append(msg),
        on_connected=lambda addr: None,
        on_disconnected=lambda: None
    )

    host_ok, _ = host_net.start_host("127.0.0.1", free_port, "alice")
    assert host_ok, "Host failed to start"
    time.sleep(0.5)

    client_net.connect_to_peer("127.0.0.1", free_port, "bob")
    # Wait for connection up to 3 seconds
    start_t = time.time()
    while not client_net.is_connected and time.time() - start_t < 3.0:
        time.sleep(0.1)
    assert client_net.is_connected, "Client failed to connect to host within 3s"

    # 1. Group message delete broadcast
    del_packet = {
        "type": "delete_message",
        "msg_id": "test_group_msg_999",
        "sender": "alice",
        "recipient": "group"
    }
    host_net.send_message(del_packet)
    time.sleep(0.5)

    found_in_client = any(
        m.get("type") == "delete_message" and m.get("msg_id") == "test_group_msg_999"
        for m in client_received if isinstance(m, dict)
    )
    assert found_in_client, "Client should receive group delete_message packet"
    print("PASS: Group delete_message successfully broadcast to client.")

    # 2. 1-to-1 message delete routing
    del_dm_packet = {
        "type": "delete_message",
        "msg_id": "test_dm_msg_888",
        "sender": "bob",
        "recipient": "alice"
    }
    client_net.send_message(del_dm_packet)
    time.sleep(0.5)

    found_in_host = any(
        m.get("type") == "delete_message" and m.get("msg_id") == "test_dm_msg_888"
        for m in host_received if isinstance(m, dict)
    )
    assert found_in_host, "Host should receive 1-to-1 delete_message packet"
    print("PASS: 1-to-1 direct delete_message successfully routed to target peer.")

    client_net.disconnect()
    host_net.disconnect()
    time.sleep(0.5)

    print("\nALL TESTS PASSED SUCCESSFULLY! 🎉")

if __name__ == "__main__":
    run_tests()
