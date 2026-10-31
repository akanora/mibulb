"""Entry point used by PyInstaller to build MiBulb.exe."""

import sys

from mibulb.gui import main

main(start_minimized="--minimized" in sys.argv, restarted="--restarted" in sys.argv)
