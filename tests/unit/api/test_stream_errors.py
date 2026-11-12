"""What a reader of the public ``Stream`` can do after ``next()`` raised."""

import pytest

from capitalcom.domain.errors import ResponseFormatError
from capitalcom.domain.streaming import Quote
from tests.fakes import FakeConnection, ack_frame, quote_frame
from tests.unit.api.stream_support import resource


def test_reading_goes_on_after_an_undecodable_frame() -> None:
    # One bad frame is the server's mistake, not a broken link: the stream stays open, and a
    # new loop over it picks up the events that followed (docs/guides/streaming.md).
    connection = FakeConnection(
        [ack_frame("1", {"GOLD": "PROCESSED"}), "not json", quote_frame("GOLD")]
    )
    streams, _, _ = resource([connection])
    with streams.connect() as stream:
        stream.subscribe_quotes(["GOLD"])
        with pytest.raises(ResponseFormatError):
            for _ in stream:
                pass
        assert not stream.closed
        assert isinstance(next(iter(stream)), Quote)
