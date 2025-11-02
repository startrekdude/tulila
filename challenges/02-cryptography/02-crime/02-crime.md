In this challenge, you will implement the [CRIME attack](https://en.wikipedia.org/wiki/CRIME) in a simplified environment simulating a web browser & web servers.

The actual CRIME attack is against the HTTP protocol over TLS. Here you will be working with a simplified Web protocol:

- In this network, `cnn` and `bank` are Web servers and `umberto` is a Web client.
- A URL is a string in the form of `cnn/today` or `secure://bank/accounts` referencing a resource held on a server. If the URL starts with `secure://`, the resource will be fetched over a secure connection (defined below). The host is the portion of the URL immediately after `secure://`, if present, and before the first `/`. (So, the hosts of the example URLs are `cnn` and `bank`.) The path is the remainder of the URL (_including_ `/`).
- To send a Web request, `umberto` will send a message to the host referenced in the URL. This message's data will have at least two keys: `method` and `path`. `method` will always be `GET` and `path` will be the path of the URL.
- `umberto` will include a third value named `cookies` in the request message if he has cookies stored for the host and security setting. If a cookie is set for `secure://host`, it will **not** be sent with requests to `host/`, and vice-versa. The relevant cookies will always be sent with a request, regardless of why it was initiated. `umberto` starts with some cookies stored; there is no way to add or delete cookies.
  - The value of the `cookies` field in a message is a string like `name₁=val₁; name₂=val₂;`.
- Upon receiving a request, the server will respond with the requested resource by sending a message to the sender of the request. This message's data will have the keys `content`, `links`, and `resources`.
  - The `content` is, for the purposes of this challenge, meaningless arbitrary data.
  - The `resources` is a list of URLs representing sub-resources. `umberto` will immediately request all of these URLs in order. However, `umberto` will **not** request the `resources` of a response that was requested when processing another response's `resources`.
  - The `links` is a list of URLs representing links to other resources. `umberto` will visit these links at some point in the future.
- If a URL starts with `secure://`, it will be fetched over a secure connection. The request will proceed as detailed above, except the request data will be serialized as JSON, **compressed with `zlib`**, and encrypted with AES-GCM using a random nonce. The message sent to the server will contain the `ct` (ciphertext), `nonce`, authentication `tag`, and `method` set to `SECURE`. All binary values will be [hex-encoded](https://docs.python.org/3/library/stdtypes.html#bytes.hex). The key used for the encryption will be a shared secret known only to the client and server; `umberto` and `bank` have such a secret.
- When a server receives a request with `method = "SECURE"`, it will decrypt it, process it as usual, and compress+encrypt the response in the same manner as the request before sending it back to the client.

**Your goal:** the solution string is `umberto`'s `auth` cookie stored for `secure://bank`. Good luck!

Note that the simulator does have a message size limit. If you see errors stating that a line exceeds the maximum length, you must rework your solution to send shorter messages.

**WARNING:** In this challenge, your agent is an interceptor. You are strongly advised **not** to send messages out of sequence. Your solution should be structured as an infinite loop that (a) `receive()`s an intercepted message; (b) processes it; and (c) issues **exactly one** `send()` or `drop()` call to handle the intercepted message. The template solution below is in this form.