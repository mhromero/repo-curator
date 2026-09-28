"""Count normalized words in the synthetic scanner-demo input."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def count_words(path: Path) -> Counter[str]:
    """Return lowercase word frequencies from a UTF-8 text file."""
    return Counter(path.read_text(encoding="utf-8").lower().split())


if __name__ == "__main__":
    sample = Path(__file__).parents[1] / "data" / "example.txt"
    print(count_words(sample))
