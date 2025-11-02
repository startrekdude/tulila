You've monitored. You've spoofed. Only one last thing to do: intercept!

An agent that is an interceptor on a network will intercept all messages sent over that network and may _modify_ or _drop_ the messages before they are delivered to their recipient. (This distinguishes interceptors from monitors, who may view but not modify messages. This is also the difference between a _passive_ and an _active_ attacker.)

You may retrieve intercepted messages using `receive()`. An intercepted message will have its `context` set to `"intercept"`.

Once you have intercepted a message, you **must** handle it before sending any other messages. You can:

1. Drop the message by calling the function `drop()` with no arguments; or
2. Modify the message, then re-send it by calling `send()`. For your convenience, the first argument of `send()` may be a `Message` object; in this case you do not have to fill in the other arguments `send()` would normally require. (So, if `msg` is an intercepted `Message` object, you may re-send it with just `send(msg)` instead of `send(msg.data, msg.recipient, msg.network, msg.sender)`.)

In all cases, intercepted messages are handled in the order they are received. For example, in the following code...

```py
msg1 = receive() # assume context == "intercept"
msg2 = receive() # assume context == "intercept"
drop()
```

...`msg1` has been dropped and `msg2` has not yet been handled.

**WARNING:** if you are an interceptor, it is **not safe** to `send()` messages out of sequence, as you may overwrite a message that you have intercepted but not yet `receive()`d. Every interceptor should be structured as a loop that `receive()`s an intercepted message and processes it, resulting in **exactly one** `send()` or `drop()` call. This is called the "one `receive()`, one `send()`" rule. It is only safe to `send()` a message out of sequence if you are **sure** there are no intercepted messages waiting to be handled (and even in this case, be advised you _can_ intercept your own messages).

The template code below implements the "one `receive()`, one `send()`" rule for safe interception.

As a strict rule, all interceptors are also spoofers.

In this challenge, two generals (`hector` and `paris`) are trying to coordinate a time to attack. You control the channel over which they much communicate; further, they can only send one word at a time (the carrier parrots they send have a limited memory capacity).

You must trick the generals into attacking at different times. Note that it is not sufficient for one general to be unaware of the time to attack; they must each be convinced to attack at a specific (but different) time. As this scenario dates from before the invention of modern time-keeping, Paris only understands times that reference the position of the Sun in the sky (noon, dawn, etc.).

*Note: You may use any of your abilities as a spoofer or interceptor to solve this challenge. However, the challenge is designed to be possible to solve by (selectively) dropping messages only, in recognition of the fact that that is the key primitive distinguishing interceptors from spoofer-monitors.*
