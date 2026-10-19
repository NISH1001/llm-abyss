from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Chunk:
    """Some text from a URL. After search the text is the snippet; later stages replace or split it."""

    url: str
    text: str
    title: str = ""
    score: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)  # query, engine, rank, date, ...
