In this challenge, you will implement an active Machine-in-the-Middle attack against the Diffie-Hellman key exchange system (as described [on Wikipedia](https://en.wikipedia.org/wiki/Diffie%E2%80%93Hellman_key_exchange#Cryptographic_explanation)).

You are Mallory. You are an interceptor in a network with Alice and Bob. To communicate securely, Alice and Bob will perform the following protocol:

1. Alice and Bob have already agreed on a group defined by prime _p_ and a generator _g_. These values are public.
2. Alice will select a random integer _x_, compute _gx = gˣ mod p_, and send it to Bob.
3. Bob will select a random integer _y_, compute _gy = gʸ mod p_, and send it to Alice.
4. Alice, upon receipt of _gy_ from Bob, will compute the _shared secret S = gyˣ mod p_.
5. Bob, upon receipt of _gx_ from Alice, will compute the shared secret _S = gxʸ mod p_.
6. The shared secret _S_ is a large integer. Alice and Bob will derive an AES key from _S_ using the function `convert_shared_secret_to_AES_key`, which is given to you.
7. Further communications between Alice and Bob will be encrypted with AES; the `encrypt_message` and `decrypt_message` functions are given to you.

Your template code has `g`, `p`, `convert_shared_secret_to_AES_key`, `encrypt_message`, and `decrypt_message` pre-defined. Your goal is to spy on Alice and Bob's communications. The _second_ message (not including the key exchange) sent from Alice to Bob is the solution (remember to submit it with `solve()`). Good luck!

**WARNING:** In this challenge, your agent is an interceptor. You are strongly advised **not** to send messages out of sequence. Your solution should be structured as an infinite loop that (a) `receive()`s an intercepted message; (b) processes it; and (c) issues **exactly one** `send()` or `drop()` call to handle the intercepted message. The template solution below is in this form.