__all__ = ["greet", "Client", "LEGACY"]
LEGACY = 1

def greet(name, punctuation="!"):
    return f"Hello {name}{punctuation}"

class Client:
    def send(self, message, *, timeout=5):
        return message
