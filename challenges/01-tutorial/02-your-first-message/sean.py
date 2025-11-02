while True:
	msg = receive()
	if msg.data.get("s", None) == "hello":
		mark_solved()
