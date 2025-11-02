from os import urandom

soln = urandom(16).hex()
set_solution(soln)

for _ in range(100):
	if urandom(1)[0] < 85:
		send({"data": soln}, "george")
	else:
		send({"data": urandom(16).hex()}, "fred")
	receive()

while True: receive()
