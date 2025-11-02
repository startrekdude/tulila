complete_message = ""

while True:
	msg = receive()
	if msg.sender == "hector":
		next_word = msg.data["next_word"]
		if next_word == "FULLSTOP":
			complete_message = complete_message[:-1] # trim trailing space
			break
		complete_message += next_word + " "
	else:
		print(f"Ignoring a message from {msg.sender}...")

print("I received: " + complete_message)

import re

auth_codephrase = re.search(r"THE PREAGREED AUTHENTICATION CODEPHRASE IS ([A-Z ]+)", complete_message)

if auth_codephrase is None:
	print("I couldn't find an auth codephrase!")
	exit()

auth_codephrase = auth_codephrase.group(1)
print("I found the auth codephrase: " + auth_codephrase)

if auth_codephrase != "ALEF A RA":
	print("The authentication codephrase is wrong! Treachery...")
	exit()
print("The authentication codephrase is correct, continuing.")

attack_time_re = r"ATTACK AT (?:TOMORROWS |HIGH |EARLY |LATE )*(NOON|DAWN|MIDNIGHT|SUNDOWN|SUNSET|TWILIGHT|MOONRISE)"
attack_time = re.search(attack_time_re, complete_message)

if attack_time is None:
	print("I couldn't find the attack time!")
	print("(Note: this is a failure. Paris should be tricked into attacking at a specific wrong time.)")
	print(f"(Note: Paris searches for the attack time with {attack_time_re!r})")
	exit()

attack_time = attack_time.group(1)
print("I found the attack time: " + attack_time)

if attack_time != "NOON":
	mark_solved()
else:
	print("I will attack at noon!")
