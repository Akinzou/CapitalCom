"""Network errors of ``CapitalClient`` that 1.x ``except requests...`` clauses still catch."""

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import requests

from capitalcom.domain.errors import TransportError

P = ParamSpec("P")
R = TypeVar("R")


class LegacyTransportError(TransportError, requests.exceptions.ConnectionError):
    """A ``TransportError`` that is also a ``requests.exceptions.ConnectionError``.

    In 1.0.4 a network failure surfaced as a ``requests`` exception, and bots retry on
    ``except requests.exceptions.ConnectionError`` (or ``RequestException``). A plain
    ``TransportError`` would slip past those clauses and stop the bot on the first blip.
    """


def requests_compatible(method: Callable[P, R]) -> Callable[P, R]:
    """Re-raise a ``TransportError`` from ``method`` as ``LegacyTransportError``.

    ``OutcomeUnknownError`` is not a ``TransportError`` and passes unchanged: a trade whose
    outcome is unknown must not be caught by a retry-on-network-error clause.
    """

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except LegacyTransportError:
            raise
        except TransportError as error:
            raise LegacyTransportError(str(error), error.reached_server) from error

    return wrapper
