while True:
    msg = receive()
    if msg.context == "intercept":
        # Modify the message here
        send(msg)
