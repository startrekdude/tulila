from os import urandom

for _ in range(100):
	send(
		{"data": urandom(16).hex()},
		"george" if urandom(1)[0] & 1 else "neville"
	)
	receive()

while True: receive()
