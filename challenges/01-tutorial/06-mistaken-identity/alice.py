def do_balance_inquiry():
	send({"request": "inquiry"}, "bank")
	while True:
		msg = receive()
		if msg.sender == "bank": break
	bal = msg.data["result"]
	print(f"I am Alice and I have ${bal}.")

do_balance_inquiry()

while True:
	receive()
	do_balance_inquiry()
