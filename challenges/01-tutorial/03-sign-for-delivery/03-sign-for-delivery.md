Great work! Now that you've gotten the hang of sending messages, let's go over receiving them.

To receive a message, call `receive()` with no arguments. This will return a `Message` object:

```py
@dataclass
class Message:
    """Represent a message to/from another agent that was received or is to be sent.
    
    The context field represents why the message was received (direct, monitor,
    or intercept) and is not used when sending messages.
    """
    sender   : Optional[str]
    recipient: str
    network  : str
    data     : dict[str, Any]
    context  : Optional[str] = None
```

`mr_roboto` will send you the solution. Receive it and `solve()` the challenge.

*Tip: if you `print()` something, it will be visible in the log.*