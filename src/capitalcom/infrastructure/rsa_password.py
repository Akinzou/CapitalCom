"""RSA encryption of the login password, for ``encryptedPassword: true`` logins.

Capital.com documents the procedure only by a Java sample: base64 of ``password|timestamp``,
encrypted with the RSA public key the server hands out, then base64 again. The sample's prose
calls it AES, but the code uses RSA; the stage 2a contract test logs in this way against the
demo server, which pins the padding and the UTF-8 charset chosen here.

The module imports ``cryptography`` at load time and is itself imported only when encrypted
login is requested, so the dependency stays optional.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def encrypt_password(password: str, encryption_key: str, timestamp: int) -> str:
    """Return the base64 ciphertext of ``password`` for the given server key and timestamp.

    Raises ``ValueError`` when ``encryption_key`` is not a base64 DER RSA public key.
    """
    try:
        der = base64.b64decode(encryption_key, validate=True)
        key = serialization.load_der_public_key(der)
    except ValueError:  # binascii.Error is a ValueError too
        raise ValueError("encryption key is not a base64 DER public key") from None
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("encryption key is not an RSA public key")
    plain = base64.b64encode(f"{password}|{timestamp}".encode())
    # PKCS#1 v1.5 is what Java's default "RSA" cipher uses, which the documented sample relies
    # on; OAEP would be the better padding but the server would not decrypt it.
    return base64.b64encode(key.encrypt(plain, padding.PKCS1v15())).decode("ascii")
