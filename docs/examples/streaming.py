"""Streaming: live BTCUSD quotes over the WebSocket (needs ``capitalcom[streaming]``)."""

import itertools
import os

from capitalcom import CapitalCom, Environment, Gap, Quote


def main() -> None:
    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        # --8<-- [start:stream]
        with cc.stream.connect() as stream:
            stream.subscribe_quotes(["BTCUSD"])
            # Iteration blocks in this thread; keepalives and reconnects happen inside it.
            for event in itertools.islice(stream, 5):
                if isinstance(event, Quote):
                    print(f"{event.time:%H:%M:%S} {event.epic} {event.bid} / {event.offer}")
                elif isinstance(event, Gap):
                    # Prices between since and until were missed; resync what depends on them.
                    print(f"gap from {event.since:%H:%M:%S} to {event.until:%H:%M:%S}")
        # --8<-- [end:stream]


if __name__ == "__main__":
    main()
