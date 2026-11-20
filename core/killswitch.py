"""Kill switch: if a file named STOP exists in the project root, halt before any API call.

To stop a run:   New-Item STOP   (Windows PowerShell)   or   touch STOP   (Mac/Linux)
To allow runs:   Remove-Item STOP                       or   rm STOP
"""

from pathlib import Path

STOP_FILE = Path(__file__).resolve().parent.parent / "STOP"


class StopRequested(Exception):
    """Raised when the STOP file exists."""


def check() -> None:
    if STOP_FILE.exists():
        raise StopRequested(f"STOP file found ({STOP_FILE}). Halting before the next API call.")
