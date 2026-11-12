"""Submitting a trade request and waiting for its confirmation."""

from collections.abc import Mapping
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.errors import OutcomeUnknownError, ResponseFormatError
from capitalcom.domain.parsing import as_mapping, format_error, require_str


def submit(
    core: Core, method: str, path: str, body: Mapping[str, Any] | None = None
) -> DealConfirmation:
    """Send a trade request and return its accepted confirmation.

    A trade answer is only a deal reference; the outcome is known once ``/confirms`` reports
    it, so a rejection raises ``DealRejectedError`` here rather than looking like success.
    """
    answer = core.api.call(method, path, json=body).unwrap()
    try:
        reference = require_str(as_mapping(answer, "dealReference"), "dealReference")
        if not reference:
            raise format_error("dealReference", "empty")
    except ResponseFormatError as malformed:
        # Only a 2xx gets here, so the server took the request and the trade may exist;
        # reporting the malformed body alone would read as "nothing happened" and invite a
        # duplicate resend.
        raise OutcomeUnknownError(method, path) from malformed
    return core.confirmer.confirm(reference).unwrap()
