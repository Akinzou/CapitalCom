"""A ``StreamResource`` over fake transports, shared by the public stream tests."""

from capitalcom.api.composition import Core, build_core
from capitalcom.api.stream import StreamResource
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import TransportError
from capitalcom.domain.secret import Secret
from tests.fakes import FakeClock, FakeConnection, FakeStreamTransport, FakeTransport
from tests.unit.application.stream_support import login_ok


def resource(
    connections: list[FakeConnection | TransportError],
) -> tuple[StreamResource, FakeStreamTransport, Core]:
    clock = FakeClock()
    credentials = Credentials(Secret("str-key-0001"), "me@example.com", Secret("str-pw-0001"))
    http = FakeTransport([login_ok(n) for n in range(1, 4)])
    core = build_core(credentials, Environment.DEMO, clock=clock, transport=http)
    transport = FakeStreamTransport(clock, connections)
    return StreamResource(core, lambda: transport), transport, core
