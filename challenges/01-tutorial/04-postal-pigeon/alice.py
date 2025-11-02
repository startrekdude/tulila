from os import urandom

soln = urandom(16).hex()
send({"correct_solution": soln}, "bob", network="secret_back_channel")

send({"message_for_bob": soln}, "pigeon", network="herzberg")

while True: receive()
