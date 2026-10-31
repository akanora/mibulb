"""Keep only one Mi Bulb window running.

The first instance listens on a localhost port and writes it to
instance.port next to the config. A second launch connects to that port,
asks the first instance to show its window, and exits.

On Windows a named mutex is also held, so the installer can tell that
Mi Bulb is running and ask to close it before updating or uninstalling.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from typing import Callable

from .config import user_config_path

MUTEX_NAME = "MiBulbSingleInstance"
SHOW = b"mibulb-show\n"
ACK = b"mibulb-ok\n"


def _port_file() -> Path:
    return user_config_path().parent / "instance.port"


def notify_existing(show: bool = True, timeout: float = 1.0) -> bool:
    """Return True if another instance is running (and ask it to show itself)."""
    try:
        port = int(_port_file().read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall(SHOW if show else b"mibulb-ping\n")
            # Only trust the port if Mi Bulb itself answers; it may be stale.
            return sock.recv(64) == ACK
    except OSError:
        return False


class InstanceServer:
    def __init__(self, on_show: Callable[[], None]):
        self._on_show = on_show
        self._mutex = None
        if sys.platform == "win32":
            import ctypes

            self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self._port = str(self._sock.getsockname()[1])
        path = _port_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._port, encoding="ascii")
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(1.0)
                try:
                    message = conn.recv(64)
                    if message in (SHOW, b"mibulb-ping\n"):
                        conn.sendall(ACK)
                        if message == SHOW:
                            self._on_show()
                except OSError:
                    pass

    def close(self) -> None:
        self._sock.close()
        path = _port_file()
        try:
            if path.read_text(encoding="ascii").strip() == self._port:
                path.unlink()
        except OSError:
            pass
