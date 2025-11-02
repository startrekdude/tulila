Time to put what you've learned together—sending _and_ receiving messages!

`alice` wants to talk with `bob`, but she can't: `alice` is on the `herzberg` network, but `bob` is only on the `minto` network.

Fortunately, you (agent `pigeon`) are on both networks!

Forward messages from `alice` to `bob`.



So you don't have to tab around, the definitions you have seen before are included below:

```py
def send(data, recipient, network="*"):
    """Send a message to another agent.
    
    The default network of "*" will be interpreted as "all networks
    I share with the recipient" for a non-broadcast recipient.
    """
    ...
```

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

(Note that you do not have to use the `network` argument of `send` to solve this challenge. That argument is useful if you share two or more networks with the _same_ `recipient`.)