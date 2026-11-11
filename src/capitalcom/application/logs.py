"""Library logging: everything under ``capitalcom``, never configured by the library itself."""

import logging
import threading

ROOT = "capitalcom"
_MASK = "***"
_lock = threading.Lock()
_secrets: set[str] = set()


class RedactionFilter(logging.Filter):
    """Replaces every registered secret in a record's final message with ``***``."""

    def filter(self, record: logging.LogRecord) -> bool:
        with _lock:
            # Longest first, so a secret that contains another is masked whole.
            secrets = sorted(_secrets, key=len, reverse=True)
        if not secrets:
            return True
        message = record.getMessage()
        redacted = message
        for secret in secrets:
            redacted = redacted.replace(secret, _MASK)
        if redacted != message:
            # Freezing the formatted text drops args, so no handler can re-render the secret.
            record.msg, record.args = redacted, None
        return True


_FILTER = RedactionFilter()


def get_logger(name: str) -> logging.Logger:
    """Return a ``capitalcom`` logger with redaction attached.

    The filter goes on every logger rather than only the root, because a logger's filters are
    not applied to records created by its children.
    """
    root = logging.getLogger(ROOT)
    with _lock:
        if not any(isinstance(h, logging.NullHandler) for h in root.handlers):
            root.addHandler(logging.NullHandler())
    logger = logging.getLogger(name)
    if _FILTER not in logger.filters:
        logger.addFilter(_FILTER)
    return logger


def register_secret(value: str) -> None:
    """Start masking ``value`` (API key, password, issued tokens) in log output."""
    if value:
        with _lock:
            _secrets.add(value)


def forget_secret(value: str) -> None:
    """Stop masking a replaced token, so periodic re-login does not grow the registry."""
    with _lock:
        _secrets.discard(value)
