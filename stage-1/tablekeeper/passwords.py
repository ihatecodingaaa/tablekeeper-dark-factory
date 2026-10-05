"""Password hashing with scrypt (hashlib, OpenSSL-backed).

Hashes are self-describing strings `scrypt$<n>$<r>$<p>$<salt>$<digest>`
(base64url salt and digest), so exported state verifies after import.
hashlib.scrypt releases the GIL, so callers hash outside the state lock.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from concurrent.futures import ThreadPoolExecutor

# n=2**13, r=8 is ~8 MiB and ~13 ms per hash on the test host: 100 seeded users
# hash in well under 2 s on 2 vCPU, and 50 concurrent logins stay far below 5 s.
SCRYPT_N = 2 ** 13
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
_MAX_N = 2 ** 16
_MAXMEM = 128 * 1024 * 1024
_MAX_BLOCK = 32 * 1024 * 1024          # scrypt memory 128*n*r stays well under maxmem
_MAX_WORK = 4 * SCRYPT_N * SCRYPT_R    # bounded verify cost for imported hashes


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN, maxmem=_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def hash_many(passwords: list[str]) -> list[str]:
    """Hash several passwords in parallel threads; order is preserved."""
    if len(passwords) <= 1:
        return [hash_password(p) for p in passwords]
    with ThreadPoolExecutor(max_workers=min(4, len(passwords))) as pool:
        return list(pool.map(hash_password, passwords))


def _parse(stored: str):
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, digest = _unb64(parts[4]), _unb64(parts[5])
    except (ValueError, TypeError):
        return None
    if not (2 <= n <= _MAX_N and n & (n - 1) == 0 and 1 <= r <= 16 and 1 <= p <= 4):
        return None
    if 128 * n * r > _MAX_BLOCK or n * r * p > _MAX_WORK:
        return None
    if not salt or len(digest) != DKLEN:
        return None
    return n, r, p, salt, digest


def is_valid_hash(stored) -> bool:
    return isinstance(stored, str) and len(stored) <= 512 and _parse(stored) is not None


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse(stored) if isinstance(stored, str) else None
    if parsed is None:
        return False
    n, r, p, salt, digest = parsed
    candidate = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=n, r=r, p=p,
                               dklen=DKLEN, maxmem=_MAXMEM)
    return hmac.compare_digest(candidate, digest)
