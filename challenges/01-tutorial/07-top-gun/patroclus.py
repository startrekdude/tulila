while True:
    msg = receive()
    if msg.context == "intercept":
        # Modify the intercepted message here
        send(msg)
