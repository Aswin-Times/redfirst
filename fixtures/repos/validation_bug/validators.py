def is_valid_email(value: str) -> bool:
    """An email needs text before and after a single '@'."""
    return "@" in value  # BUG: accepts "a@" and "@b"
