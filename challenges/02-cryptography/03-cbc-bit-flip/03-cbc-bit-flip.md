_This challenge is based on an assignment question from Dr. Jason Hinek's Fall 2024 offering of COMP 2108: Applied Cryptography and Authentication. Thanks Jason!_

Introducing RavenPay™: a new online service that lets you transfer money to other people from the comfort of your home.

A RavenPay client sends money using the following protocol:

1. The RavenPay client constructs a string of the form "`send $XX to YYYYYYYYY from ZZZZZZZZZ`" and encrypts it with AES in CBC mode using the key they share with the server and a randomly-selected IV. Standard PKCS#7 padding will be used.
   - `ZZZZZZZZZ` is the RavenPay client's 9-digit account number.
   - `YYYYYYYYY` is the 9-digit account number of the intended recipient of the transfer.
   - `XX` is the amount of money to transfer. It must always be exactly two digits, but it can start with "0".
2. The RavenPay client sends a message to the `raven-pay` agent. This message's data should have two fields:
   1. `request_ct`, the request ciphertext as constructed above (hex-encoded).
   2. `iv`, the randomly selected initialization vector (hex-encoded).

_You_ are not a RavenPay client. You are interested in subverting the system. You have learned that today is bill-payment day for `audrey`, a local small business owner, and she will send the following transfers (in the following order):

1. $10 to 575562148
2. $5 to 575562148
3. $32 to 493048101
4. $60 to 218143001
5. $52 to 697465148
6. $77 to 278548226
7. $11 to 620163291
8. $70 to 697465148
9. $91 to 218143001
10. $24 to 493048101
11. $52 to 278548226
12. $76 to 575562148
13. $20 to 883902551

You also know that `audrey`'s account number is 999999937.

You have the ability to intercept and modify messages `audrey` sends to `raven-pay`. Your goal is to, by the end of the day, make it so that the following accounts have the specified balances:

1. 999562148 should have $170
2. 627562148 should have $33
3. 395048101 should have $108
4. 000143001 should have $78
5. 191143001 should have $1
6. 697465148 should have $91
7. 278548226 should have $112
8. 420902551 should have $43

You may assume all of these accounts start the day with $0. Good luck!

**WARNING:** In this challenge, your agent is an interceptor. You are strongly advised **not** to send messages out of sequence. Your solution should be structured as an infinite loop that (a) `receive()`s an intercepted message; (b) processes it; and (c) issues **exactly one** `send()` or `drop()` call to handle the intercepted message. The template solution below is in this form.