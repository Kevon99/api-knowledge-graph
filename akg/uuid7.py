"""UUID v7 implementation for Python < 3.14."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a UUID v7 (time-ordered) using millisecond timestamp + random bytes."""
    timestamp_ms = int(time.time() * 1000)
    random_bytes = os.urandom(10)

    hex_digits = f"{timestamp_ms:012x}{random_bytes.hex()}"

    u = uuid.UUID(hex=hex_digits)
    return uuid.UUID(
        fields=(
            u.time_low,
            u.time_mid,
            (u.time_hi_version & 0x0FFF) | 0x7000,
            u.clock_seq_hi_variant,
            u.clock_seq_low,
            u.node,
        )
    )
