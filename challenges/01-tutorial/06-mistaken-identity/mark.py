send({
	"request": "transfer",
	"amount": 300,
	"to": "alice",
}, "bank")

while True:
	msg = receive()
	if msg.sender == "bank" and msg.data.get("result") == "TRANSFER_SUCCESSFUL":
		send({"sms": "Hi honey, I sent you the money for the plumber"}, "alice")
