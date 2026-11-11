"""Result type used between ports and services; only the public facade unwraps it."""

from dataclasses import dataclass
from typing import Generic, NoReturn, TypeAlias, TypeVar

from capitalcom.domain.errors import CapitalComError

T = TypeVar("T")
E = TypeVar("E", bound=CapitalComError)


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    """A successful outcome carrying ``value``."""

    value: T

    def unwrap(self) -> T:
        """Return the value."""
        return self.value


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    """A failed outcome carrying ``error``."""

    error: E

    def unwrap(self) -> NoReturn:
        """Raise the error; this is where internal results become public exceptions."""
        raise self.error


Result: TypeAlias = Ok[T] | Err[E]
