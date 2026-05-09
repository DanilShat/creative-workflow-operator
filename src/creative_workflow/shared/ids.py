"""Small ID helpers for durable records.

Readable prefixes make operator logs and artifact paths easier to inspect while
UUID randomness avoids coordination problems between API calls and workers.
"""

from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"

