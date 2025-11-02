from random import choice, randint
from string import ascii_uppercase, ascii_lowercase, digits


identity = "cnn"
resource_extensions = [".png", ".jpg", ".css", ".mp4", ".js"]
links = {
	"/today": [
		"/international",
		"/local",
		"/pictures",
		"/funny",
		"/yesterday",
	],
	"/international": [
		"/international/san_marino",
		"/international/sao_tome_and_principe",
		"/international/germany",
		"/international/greenland",
	],
	"/international/greenland": [
		"/ice",
		"/polar_bears",
		"/cuisine/hakarl",
	],
	"/local": [
		"/canada",
		"/ontario",
		"/ottawa",
	],
	"/ottawa": [
		"/transit/horrible",
		"/news/protests/cuasa",
	],
	"/ontario": [
		"/toronto/leafs/loss_record",
		"/news/election",
	],
	"/pictures": [
		"/pictures/cats",
		"/pictures/dogs",
		"/pictures/foxes",
	],
	"/pictures/foxes": [
		"/pictures/foxes/eating",
		"/pictures/foxes/swimming",
		"/pictures/foxes/sleeping",
	],
	"/pictures/foxes/sleeping": [
		"/pictures/foxes/sleeping/on_car_rides",
	],
	"/funny": [
		"/funny/comedy",
		"/funny/ironic",
		"/funny/wliia",
	],
	"/funny/wliia": [
		"/pictures/arctic_tern",
	],
}
links["/yesterday"] = ["/yesterday" + x for x in links.keys()]
links.update({
	"/yesterday" + k: ["/yesterday" + x for x in v]
	for k, v in links.items()
})


def random_resource():
	return identity + "/" + "".join(
		choice(ascii_lowercase + ascii_uppercase + digits)
		for _ in range(randint(3,8))
	) + choice(resource_extensions)


def random_content(path):
	for ext in resource_extensions:
		if path.endswith(ext):
			return f"A {ext} file."
	word_count = randint(5, 100)
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
	if not any(request["path"].endswith(ext) for ext in resource_extensions):
		response["resources"] = [random_resource() for _ in range(randint(3,8))]
	return response


while True:
	request = receive()
	method = request.data.get("method")
	if method == "GET":
		send(handle_request(request.data), request.sender, network="internet")
	else:
		print(f"Unknown method: {method}")
