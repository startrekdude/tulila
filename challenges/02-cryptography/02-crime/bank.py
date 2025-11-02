import json
import zlib

from random import choice, randint
from string import ascii_uppercase, ascii_lowercase, digits

from Crypto.Cipher import AES


identity = "bank"
resource_extensions = [".png", ".jpg", ".css", ".mp4", ".js"]
links = {
	"/accounts": [
		"/chequing",
		"/savings",
		"/line_of_credit",
		"/credit_cards",
		"/privacy",
		"/tos",
	],
	"/chequing": [
		"/debit_card",
		"/chequing/transactions",
		"/chequing/overdraft",
		"/chequing/order_cheques",
	],
	"/debit_card": [
		"/debit_card/report_lost",
		"/debit_card/report_stolen",
	],
	"/savings": [
		"/savings/Emergency%20Fund",
		"/savings/Trip%20South",
		"/savings/promotions",
		"/savings/transfer",
	],
	"/savings/promotions": [
		"/savings/rate_tiers",
		"/savings/earn_more",
	],
	"/line_of_credit": [
		"/line_of_credit/transactions",
		"/line_of_credit/statements",
		"/line_of_credit/current_rate",
	],
	"/line_of_credit/current_rate": [
		"/rates",
	],
	"/credit_cards": [
		"/credit_cards/my",
		"/credit_cards/apply",
	],
	"/credit_cards/my": [
		"/credit_cards/my/cash_back_visa",
	],
	"/credit_cards/my/cash_back_visa": [
		"/credit_cards/my/cash_back_visa/statements",
		"/credit_cards/my/cash_back_visa/transactions",
		"/credit_cards/my/cash_back_visa/insurance/claim",
	],
	"/credit_cards/apply": [
		"/credit_cards/world_elite_points",
		"/credit_cards/secured_credit",
		"/credit_cards/manage_authorized_users",
	],
}
shared_secrets = {}


def random_resource():
	return identity + "/" + "".join(
		choice(ascii_lowercase + ascii_uppercase + digits)
		for _ in range(randint(3,8))
	) + choice(resource_extensions)


def random_content(path):
	for ext in resource_extensions:
		if path.endswith(ext):
			return f"A {ext} file."
	word_count = randint(5, 80)
	return " ".join(
		"".join(choice(ascii_lowercase) for _ in range(randint(3, 12)))
		for _ in range(word_count)
	)


def handle_request(request):
	response = {
		"content": random_content(request["path"]),
		"links": [],
		"resources": [],
	}
	
	if request["path"] in links:
		response["links"] = [identity + link for link in links[request["path"]]]
		response["resources"] = [random_resource() for _ in range(randint(3,8))]
	return response


def handle_encrypted_request(request, sender):
	if sender not in shared_secrets:
		raise ValueError(f"do not have a shared secret with {sender}")
	key = shared_secrets[sender]
	
	ct = bytes.fromhex(request["ct"])
	tag = bytes.fromhex(request["tag"])
	nonce = bytes.fromhex(request["nonce"])
	
	cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
	request = json.loads(zlib.decompress(cipher.decrypt_and_verify(ct, tag)).decode())
	
	response = handle_request(request)
	response["resources"] = ["secure://" + url for url in response["resources"]]
	response["links"] = ["secure://" + url for url in response["links"]]
	
	response_bytes = zlib.compress(json.dumps(response).encode())
	cipher = AES.new(key, AES.MODE_GCM)
	ct, tag = cipher.encrypt_and_digest(response_bytes)
	return {
		"ct"    : ct.hex(),
		"tag"   : tag.hex(),
		"nonce" : cipher.nonce.hex(),
	}


while True:
	request = receive()
	
	if "secret" in request.data and request.sender not in shared_secrets \
	   and (request.sender != "umberto" or request.network == "challenge_init"):
		shared_secrets[request.sender] = bytes.fromhex(request.data["secret"])
		continue
	
	method = request.data.get("method")
	if method == "GET":
		send(handle_request(request.data), request.sender, network="internet")
	elif method == "SECURE":
		send(handle_encrypted_request(request.data, request.sender), request.sender, network="internet")
	else:
		print(f"Unknown method: {method}")
