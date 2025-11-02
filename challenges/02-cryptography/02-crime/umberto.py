import json
import zlib

from collections import deque
from dataclasses import dataclass
from os import urandom

from Crypto.Cipher import AES


solution = urandom(12).hex()
set_solution(solution)
print(f"The solution is: {solution}")

cookie_jar = {
	"secure://bank": f"auth={solution};",
	"cnn": f"analytics-sid={urandom(8).hex()};"
}

shared_secrets = {
	"bank": urandom(16)
}

valid_hosts = frozenset(["bank", "cnn"])

send({"secret": shared_secrets["bank"].hex()}, "bank", network="challenge_init")


@dataclass(frozen=True)
class ParsedURL:
	is_secure: bool
	host     : str
	path     : str
	
	@property
	def cookie_key(self):
		if self.is_secure:
			return "secure://" + self.host
		return self.host
	
	@staticmethod
	def from_string(s):
		is_secure = False
		if s.startswith("secure://"):
			is_secure = True
			s = s[9:]
		
		sep = s.find("/")
		if sep == "-1":
			host = s
			path = "/"
		else:
			host = s[:sep]
			path = s[sep:]
		
		return ParsedURL(is_secure, host, path)


def send_encrypted_request(url, request):
	request_bytes = zlib.compress(json.dumps(request).encode(), 9)
	
	if url.host not in shared_secrets:
		raise ValueError(f"cannot send encrypted request to host {url.host}")
	key = shared_secrets[url.host]
	
	cipher = AES.new(key, AES.MODE_GCM)
	ct, tag = cipher.encrypt_and_digest(request_bytes)
	encrypted_request = {
		"method": "SECURE",
		"ct"    : ct.hex(),
		"tag"   : tag.hex(),
		"nonce" : cipher.nonce.hex(),
	}
	
	send(encrypted_request, url.host, network="internet")
	encrypted_response = receive()
	assert encrypted_response.sender == url.host
	
	d = encrypted_response.data
	cipher = AES.new(key, AES.MODE_GCM, nonce=bytes.fromhex(d["nonce"]))
	pt = zlib.decompress(cipher.decrypt_and_verify(bytes.fromhex(d["ct"]), bytes.fromhex(d["tag"])))
	return json.loads(pt.decode())


def send_request(url):
	url = ParsedURL.from_string(url)
	request = {
		"method" : "GET",
		"path"   : url.path
	}
	if url.cookie_key in cookie_jar:
		request["cookies"] = cookie_jar[url.cookie_key]
	if url.host not in valid_hosts:
		raise ValueError(f"Invalid host: {url.host}")
	
	if url.is_secure:
		return send_encrypted_request(url, request)
	else:
		send(request, url.host, network="internet")
		response = receive()
		assert response.sender == url.host
		return response.data
	

request_queue = deque(["secure://bank/accounts", "cnn/today"])
while request_queue:
	url = request_queue.popleft()
	response = send_request(url)
	for resource_url in response["resources"]:
		send_request(resource_url)
	for link_url in response["links"]:
		request_queue.append(link_url)
	