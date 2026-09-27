"""Convenience entry point: lets you run `python main.py` directly from the
project root, in addition to `python -m ebay_bot` or the installed `ebay-bot`
console script. Works whether or not the package has been pip installed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ebay_bot.main import main  # noqa: E402

if __name__ == "__main__":
    main()
