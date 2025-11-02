soln = None

while True:
	msg = receive()
	if msg.sender == "alice" and "correct_solution" in msg.data:
		soln = msg.data["correct_solution"]
	elif "message_for_bob" in msg.data:
		if msg.data["message_for_bob"] == soln:
			mark_solved()
