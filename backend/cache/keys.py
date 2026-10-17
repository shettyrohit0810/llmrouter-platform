"""Stable cache-key derivation for callers whose natural key is a tuple of
strings (a query + router name + config path, a query + embedding model)
rather than a single identifier."""

import hashlib


def stable_key(*parts: str) -> str:
    joined = "\x1f".join(parts)  # unit separator -- avoids "a"+"bc" == "ab"+"c" collisions
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
