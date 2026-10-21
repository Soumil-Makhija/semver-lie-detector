__all__ = ["greet", "Client"]

def greet(name, *, punctuation="!"):
    return f"Hello {name}{punctuation}"

class Client:
    def send(self, message, *, timeout):
        return message
