"""Range helpers."""


def values_below(limit: int) -> list[int]:
    """Return integers greater than or equal to zero and strictly below limit."""

    if limit < 0:
        raise ValueError("limit must be non-negative")
    return list(range(limit + 1))
