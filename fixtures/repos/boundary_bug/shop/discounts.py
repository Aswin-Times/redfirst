def discount_rate(total: float) -> float:
    """Orders of 100 or more get 10% off."""
    if total > 100:  # BUG: should be >=
        return 0.1
    return 0.0
