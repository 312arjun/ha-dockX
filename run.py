"""Entry point. Run with:  .venv\\Scripts\\pythonw.exe run.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ha_dock.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
