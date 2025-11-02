import re

from collections import defaultdict
from os import urandom

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


shared_secrets = {
	"audrey": urandom(16)
}
account_owners = {
	"999999937": "audrey",
}
account_balance = defaultdict(lambda: 0, {
	"999999937": 8675309
})

send({"secret": shared_secrets["audrey"].hex()}, "audrey", network="challenge_init")

parse_request = re.compile(r"send \$(?P<amount>\d\d) to (?P<tx_dest>\d{9}) from (?P<tx_src>\d{9})").fullmatch


def check_if_solved():
	return (
		    account_balance["999562148"] == 170
		and account_balance["627562148"] == 33
		and account_balance["395048101"] == 108
		and account_balance["000143001"] == 78
		and account_balance["191143001"] == 1
		and account_balance["697465148"] == 91
		and account_balance["278548226"] == 112
		and account_balance["420902551"] == 43
	)


while True:
	msg = receive()
	try:
		request_ct = bytes.fromhex(msg.data["request_ct"])
		cipher = AES.new(shared_secrets[msg.sender], AES.MODE_CBC, iv=bytes.fromhex(msg.data["iv"]))
		request = unpad(cipher.decrypt(request_ct), AES.block_size).decode()
		
		parts   = parse_request(request).groupdict()
		amount  = int(parts["amount"])
		tx_dest = parts["tx_dest"]
		tx_src  = parts["tx_src"]
		
		if account_owners[tx_src] != msg.sender:
			raise ValueError("invalid account")
		
		account_balance[tx_src] -= amount
		account_balance[tx_dest] += amount
		print(f"Transferred ${amount} to {tx_dest} from {tx_src}.")
		
		if check_if_solved():
			mark_solved()
		print(account_balance)
	except Exception:
		print(f"Error: unable to process {msg.data} from {msg.sender}")