"""The websockets adapter against a local TLS server with a throwaway certificate."""

import datetime
import ipaddress
import logging
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from websockets.sync.server import ServerConnection, serve

from capitalcom.application.logs import forget_secret, register_secret
from capitalcom.application.result import Err, Ok
from capitalcom.application.session import SessionTokens
from capitalcom.application.stream_frames import encode_frame
from capitalcom.domain.errors import TransportError, ValidationError
from capitalcom.domain.secret import Secret
from capitalcom.infrastructure.websocket_transport import WebsocketTransport

# An address, not "localhost": on Windows the name resolves to ::1 first and every connect
# would wait for the IPv6 attempt to fail.
HOST = "127.0.0.1"


def _certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.datetime.now(datetime.UTC)
    public = key.public_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(public), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _handle(connection: ServerConnection) -> None:
    path = connection.request.path if connection.request else "/"
    if path == "/close":
        connection.close(1000, "bye")
    elif path == "/echo":
        for message in connection:
            connection.send(message)
    else:
        connection.recv()


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    cert, key = _certificate(tmp_path_factory.mktemp("tls"))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    # The server logs the frames it receives, tokens included; the library is what is tested.
    quiet = logging.getLogger("tests.websocket_server")
    quiet.disabled = True
    with serve(_handle, HOST, 0, ssl=context, logger=quiet) as running:
        thread = threading.Thread(target=running.serve_forever, daemon=True)
        thread.start()
        port = running.socket.getsockname()[1]
        yield f"wss://{HOST}:{port}", cert
        running.shutdown()


def test_round_trip_with_ca_bundle_path(server: tuple[str, Path]) -> None:
    url, cert = server
    connected = WebsocketTransport(str(cert)).connect(f"{url}/echo")
    assert isinstance(connected, Ok)
    connection = connected.value
    assert connection.send("hello") == Ok(None)
    assert connection.receive(5.0) == Ok("hello")
    connection.close()
    connection.close()


def test_unknown_certificate_is_refused(server: tuple[str, Path]) -> None:
    url, _ = server
    connected = WebsocketTransport().connect(f"{url}/echo")
    assert isinstance(connected, Err)
    assert isinstance(connected.error, TransportError)
    assert not connected.error.reached_server


def test_receive_timeout_is_ok_none(server: tuple[str, Path]) -> None:
    url, cert = server
    connected = WebsocketTransport(str(cert)).connect(f"{url}/silent")
    assert isinstance(connected, Ok)
    assert connected.value.receive(0.05) == Ok(None)
    connected.value.close()


def test_server_close_reached_server_true(server: tuple[str, Path]) -> None:
    url, cert = server
    connected = WebsocketTransport(str(cert)).connect(f"{url}/close")
    assert isinstance(connected, Ok)
    received = connected.value.receive(5.0)
    assert isinstance(received, Err)
    assert received.error.reached_server
    assert isinstance(connected.value.send("late"), Err)


def test_ws_scheme_refused() -> None:
    with pytest.raises(ValidationError, match="wss"):
        WebsocketTransport().connect("ws://localhost:1/connect")


@pytest.mark.parametrize("verify", [False, ""])
def test_tls_verification_cannot_be_switched_off(verify: bool | str) -> None:
    with pytest.raises(ValidationError, match="TLS"):
        WebsocketTransport(verify)


def test_debug_logging_never_shows_tokens(
    server: tuple[str, Path], caplog: pytest.LogCaptureFixture
) -> None:
    url, cert = server
    cst, xst = "CSTtoken" + "c" * 40, "XSTtoken" + "x" * 40
    tokens = SessionTokens(Secret(cst), Secret(xst), 1)
    register_secret(cst)
    register_secret(xst)
    caplog.set_level(logging.DEBUG)
    try:
        connected = WebsocketTransport(str(cert)).connect(f"{url}/echo")
        assert isinstance(connected, Ok)
        frame = encode_frame("ping", "1", tokens, None)
        assert connected.value.send(frame) == Ok(None)
        assert connected.value.receive(5.0) == Ok(frame)
        connected.value.close()
    finally:
        forget_secret(cst)
        forget_secret(xst)
    assert any(r.name == "capitalcom.websocket" for r in caplog.records)
    # Frame dumps are cut to a fixed length, so a masked token could still leak in part.
    for fragment in ("CSTtoken", "XSTtoken", "c" * 12, "x" * 12):
        assert fragment not in caplog.text
