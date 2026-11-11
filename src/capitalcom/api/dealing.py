"""Submitting a trade request and waiting for its confirmation."""

from collections.abc import Mapping
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.parsing import as_mapping, require_str


def submit(
    core: Core, method: str, path: str, body: Mapping[str, Any] | None = None
) -> DealConfirmation:
    """Send a trade request and return its accepted confirmation.

    A trade answer is only a deal reference; the outcome is known once ``/confirms`` reports
    it, so a rejection raises ``DealRejectedError`` here rather than looking like success.
    """
    answer = core.api.call(method, path, json=body).unwrap()
    reference = require_str(as_mapping(answer, "dealReference"), "dealReference")
    return core.confirmer.confirm(reference).unwrap()
