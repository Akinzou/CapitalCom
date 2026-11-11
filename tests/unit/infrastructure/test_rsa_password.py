"""RSA password encryption, checked by decrypting with the matching private key."""

import base64

import pytest
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from capitalcom.domain.errors import ValidationError
from capitalcom.infrastructure.rsa_password import encrypt_password


def test_encrypt_password_round_trips() -> None:
    # PKCS#1 v1.5 output is random, so comparing ciphertexts would prove nothing; decrypting
    # with the private key is the only check that the server can read what is sent.
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key = base64.b64encode(der).decode()
    ciphertext = encrypt_password("pw", key, 1647440528194)
    plain = private.decrypt(base64.b64decode(ciphertext), padding.PKCS1v15())
    assert base64.b64decode(plain) == b"pw|1647440528194"


@pytest.mark.parametrize("key", ["not base64 !", base64.b64encode(b"not a key").decode()])
def test_bad_key_raises_value_error(key: str) -> None:
    with pytest.raises(ValueError, match="encryption key"):
        encrypt_password("pw", key, 1)


def test_non_rsa_key_raises_value_error() -> None:
    der = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(ValueError, match="not an RSA public key"):
        encrypt_password("pw", base64.b64encode(der).decode(), 1)


def test_unsupported_key_type_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def unsupported(data: bytes) -> object:
        raise UnsupportedAlgorithm("unknown key type")

    monkeypatch.setattr(serialization, "load_der_public_key", unsupported)
    with pytest.raises(ValueError, match="encryption key"):
        encrypt_password("pw", base64.b64encode(b"key").decode(), 1)


def test_password_too_long_for_the_key_is_validation_error() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # noqa: S505 - small key, short limit
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with pytest.raises(ValidationError, match="too long"):
        encrypt_password("x" * 200, base64.b64encode(der).decode(), 1)
