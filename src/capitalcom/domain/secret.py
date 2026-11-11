"""Wrapper that keeps credentials and tokens out of reprs, tracebacks and logs."""

import hmac


class Secret:
    """A sensitive string that never shows its value unless ``reveal()`` is called.

    A plain slotted class rather than a frozen dataclass: a dataclass with ``eq`` regenerates
    ``__hash__`` from the field, which would make the value recoverable by hash comparison and
    usable as a dict key that leaks into debug output.
    """

    __slots__ = ("_value",)
    __hash__ = None  # type: ignore[assignment]
    _value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Secret is immutable")

    def reveal(self) -> str:
        """Return the plain value; call only where it is put on the wire."""
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        # Constant-time comparison: equality on secrets must not leak a prefix through timing.
        return hmac.compare_digest(self._value.encode(), other._value.encode())
