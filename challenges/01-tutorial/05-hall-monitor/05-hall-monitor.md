Excellent work thus far! You've figured out the basics. On to more advanced things...

In this challenge you are a _monitor_ on a network. This means that you will receive a copy of all messages sent on the network—_even those that are not addressed to you_.

To receive a message as a monitor, just call `receive()`—this will always return the next available message. To verify you've received it as a monitor, check that the `context` field of the received message is equal to `"monitor"`.

In this challenge, agents `fred`, `neville`, and `george` are communicating over a network that you monitor. Messages sent from `neville` to `george` have the solution. Good luck!

*Tip: recall that the `Message` type has `sender` and `recipient` fields. You will need to `receive()` more than one message.*