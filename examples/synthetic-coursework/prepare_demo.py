"""Create and remove disposable files used by the public scanner demo."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parent
DISPOSABLE_PATHS = (ROOT / ".DS_Store", ROOT / "editor.swp")


def main() -> None:
    if sys.argv[1:] == ["--clean"]:
        for path in DISPOSABLE_PATHS:
            path.unlink(missing_ok=True)
        print("Removed synthetic disposable files.")
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: prepare_demo.py [--clean]")

    (ROOT / ".DS_Store").write_bytes(b"synthetic demo metadata\n")
    (ROOT / "editor.swp").write_text("synthetic editor swap file\n", encoding="utf-8")
    print("Created synthetic disposable files: .DS_Store, editor.swp")


if __name__ == "__main__":
    main()
