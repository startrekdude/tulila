Are you any good at disguises? In this challenge, your agent is _great_ at them...

Your agent is a _spoofer_ on the "internet" network in this challenge. That means that you can send messages that appear as if they were sent from another agent.

When I showed you the definition of the `send` function earlier, I cut some bits out. Now that you've made it this far, you're ready for the _full_ definition of the `send` function:

```py
def send(message_or_data, recipient=None, network="*", sender=None):
    """Send a message to another agent (or modify an intercepted message).
    
    The default network of "*" will be interpreted by the simulator code as "all
    networks I share with the recipient" for a non-broadcast recipient.
    
    You may broadcast to all recipients with "*", either on a given network
    or all networks (again with "*").
    """
    ...
```

To spoof the sender of a message, specify an explicit value for the `sender` argument naming another agent. This will only work if you are a spoofer on the network!

At the start of this challenge, `mark` has $12,000 in the bank, `alice` has $300, and you (`chuck`) have $0. To solve the challenge, increase your balance to over $9000.

To figure out the format of the message you must spoof, you may look at the source code for the other agents below or use your monitor privileges (for this challenge, you are also granted monitor privileges on "internet". Note that it is possible to be a spoofer but not a monitor.).

**Caution:** if you send a message then immediately exit, the simulation _may_ end before your message is processed. It may be wise to wait for an acknowledgement from the bank before exiting.

