class Registry:
    def __init__(self):
        self.users = {}


def register(data: dict, registry: Registry | None = None) -> str:
    """Register a user. Should raise ValueError when username is missing or empty."""
    registry = registry or Registry()
    username = data["username"]  # BUG: KeyError instead of a validation error
    if not username:
        raise ValueError("username is required")
    registry.users[username] = data.get("email")
    return username
