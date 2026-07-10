from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python tools/generate_icon.py <input_png> <output_ico>")
        return 1

    input_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()

    if not input_path.exists():
        print(f"Input PNG not found: {input_path}")
        return 1

    app = QGuiApplication([])
    image = QImage(str(input_path))
    if image.isNull():
        print(f"Failed to load image: {input_path}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = image.save(str(output_path), "ICO")
    if not ok:
        print(f"Failed to save ICO: {output_path}")
        return 1

    print(f"Generated icon: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
