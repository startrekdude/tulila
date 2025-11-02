balances = {
	"mark": 12_000,
	"alice": 300,
	"chuck": 0,
}

while True:
	msg = receive()
	assert msg.context == "direct"
	
	if msg.sender not in balances:
		continue
	
	request = msg.data.get("request", None)
	if request == "transfer":
		amount = msg.data.get("amount", None)
		if not isinstance(amount, int):
			send({"result": "BAD_REQUEST"}, msg.sender)
			continue
		
		tx_recipient = msg.data.get("to", None)
		if tx_recipient not in balances:
			send({"result": "BAD_REQUEST"}, msg.sender)
			continue
		
		if balances[msg.sender] < amount:
			send({"result": "INSUFFICIENT_BALANCE"}, msg.sender)
		else:
			balances[msg.sender] -= amount
			balances[tx_recipient] += amount
			send({"result": "TRANSFER_SUCCESSFUL"}, msg.sender)
			
			# Check if the challenge has been solved
			if balances["chuck"] > 9000:
				mark_solved()
	elif request == "inquiry":
		send({"result": balances[msg.sender]}, msg.sender)
