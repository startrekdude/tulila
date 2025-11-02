from os import urandom

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

while True:
	msg = receive()
	if msg.sender == "raven-pay" and msg.network == "challenge_init":
		key = bytes.fromhex(msg.data["secret"])
		break

my_account_number = "999999937"

def transfer_money(amount, to):
	assert len(amount) == 2
	assert len(to) == 9
	request = f"send ${amount} to {to} from {my_account_number}"
	iv = urandom(16)
	request_ct = AES.new(key, AES.MODE_CBC, iv=iv).encrypt(pad(request.encode(), AES.block_size))
	send({
		"request_ct": request_ct.hex(),
		"iv": iv.hex(),
	},  "raven-pay", network="herzberg")

transfer_money("10", "575562148")
transfer_money("05", "575562148")
transfer_money("32", "493048101")
transfer_money("60", "218143001")
transfer_money("52", "697465148")
transfer_money("77", "278548226")
transfer_money("11", "620163291")
transfer_money("70", "697465148")
transfer_money("91", "218143001")
transfer_money("24", "493048101")
transfer_money("52", "278548226")
transfer_money("76", "575562148")
transfer_money("20", "883902551")
