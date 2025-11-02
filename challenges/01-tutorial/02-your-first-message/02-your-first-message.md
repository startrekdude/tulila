Now that you've learned how to use `solve()`, it is time to learn something more complicated: sending messages!

In this challenge you are in a network with _another_ agent, `sean` the solver. You do not have permission to solve the challenge, but he does!

`send` is defined as follows:

```py
def send(data, recipient, network="*"):
    """Send a message to another agent.
    
    The default network of "*" will be interpreted as "all networks
    I share with the recipient" for a non-broadcast recipient.
    """
    ...
```

The `data` within a message is a standard Python dictionary. `sean` will solve this challenge for you if you send him a message with key `s` and value `hello`.

Note that `send` expects `recipient` to be a string; `send(..., sean)` is an error (`sean` should be in quotes).

**Caution:** if you send a message then immediately exit, the simulation _may_ end before your message is processed. To (deterministically) avoid this, add `receive()` at the end of your submission. You will learn about `receive()` later.

*Tip: `sean` is an agent just like you. If you think it would be helpful to see `sean`'s code, it is available below.*