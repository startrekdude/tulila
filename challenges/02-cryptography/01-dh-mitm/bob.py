from hashlib import sha256
from os import urandom
from random import SystemRandom

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# p and g define the 2048-bit MODP group from RFC 3526
p = int(
	"FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
	"29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
	"EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
	"E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
	"EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
	"C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
	"83655D23DCA3AD961C62F356208552BB9ED529077096966D"
	"670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
	"E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
	"DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
	"15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
g = 2

# Share a secret with Alice
# This is used to force Mallory to do a key-exchange with both Bob and Alice, not just Alice
secret = urandom(16)
send({"secret": secret.hex()}, "alice", network="challenge_init")

# Calculate Bob's y and gy
y = SystemRandom().randrange(p)
gy = pow(g, y, p)
send({"gy": gy}, "alice", network="internet")

def convert_shared_secret_to_AES_key(shared_secret):
	return sha256(
		shared_secret.to_bytes((shared_secret.bit_length() + 7) // 8, "big")
	).digest()[:16]

def encrypt_message(key, message):
	iv = urandom(16)
	return {
		"iv": iv.hex(),
		"ct": AES.new(key, AES.MODE_CBC, iv=iv).encrypt(pad(message.encode(), AES.block_size)).hex()
	}

def decrypt_message(key, message):
	# This crashes if the padding is bad, ending the simulation.
	return unpad(AES.new(key, AES.MODE_CBC, iv=bytes.fromhex(message["iv"]))
	                .decrypt(bytes.fromhex(message["ct"])), AES.block_size).decode()

def xor(a, b):
	return bytes(x ^ y for x, y in zip(a, b))

key = None
while True:
	msg = receive()
	if msg.sender != "alice":
		print(f"Refusing to trust message from {msg.sender}!")
		continue
	
	if "gx" in msg.data and key is None:
		gx = msg.data["gx"]
		key = convert_shared_secret_to_AES_key(pow(gx, y, p))
		continue
	
	if "ct" in msg.data and "iv" in msg.data:
		if key is None:
			print("I cannot decrypt this message as we have not established a key!")
			continue
		pt = decrypt_message(key, msg.data)
		if pt.startswith("handshake_1_"):
			cookie = pt[12:]
			send(
				encrypt_message(key, "handshake_2_" + xor(secret, bytes.fromhex(cookie)).hex()),
				"alice",
				network="internet"
			)
			