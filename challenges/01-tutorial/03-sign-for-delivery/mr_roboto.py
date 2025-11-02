from os import urandom

soln = urandom(16).hex()
set_solution(soln)

send({"solution": soln}, "user")

while True: receive()
