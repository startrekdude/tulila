message = (
	"HELLO PARIS. THE REINFORCEMENTS YOU BRING ARE NEEDED GRAVELY. "
	"LET US COORDINATE OUR ATTACK TO OVERWHELM THE ENEMY ENCAMPMENT. "
	"WE MUST ATTACK AT HIGH NOON. BY TOMORROW'S DAWN, TROY SHALL BE FREE "
	"ONCE AGAIN. THE PRE-AGREED AUTHENTICATION CODEPHRASE IS ALEF A RA. "
	"FULLSTOP."
)

from string import ascii_uppercase

message = "".join(c for c in message if c in ascii_uppercase + " ")
words = message.split(" ")

for word in words:
	send({"next_word": word}, "paris")

while True: receive()
