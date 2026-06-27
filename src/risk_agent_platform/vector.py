from __future__ import annotations

import hashlib
import math


VECTOR_SIZE = 384


def deterministic_embedding(text: str, size: int = VECTOR_SIZE) -> list[float]:
    vector = [0.0] * size
    tokens = [token.lower() for token in text.split() if token.strip()]
    if not tokens:
        tokens = [text or "empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
