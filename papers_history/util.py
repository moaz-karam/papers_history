"""Small helpers: launching Papers, formatting dates and sizes."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_VIEWER = "papers"
VIEWER_ENV = "PAPERS_HISTORY_VIEWER"


class ViewerNotFound(RuntimeError):
    """Raised when the configured PDF viewer cannot be executed."""


def viewer_command() -> str:
    """Viewer binary, overridable with ``$PAPERS_HISTORY_VIEWER``."""
    return os.environ.get(VIEWER_ENV) or DEFAULT_VIEWER


def launch_viewer(path: str | os.PathLike[str]) -> subprocess.Popen:
    """Open ``path`` in Papers, with the viewer's cwd set to the PDF's folder."""
    target = Path(path).expanduser()
    command = viewer_command()

    resolved = shutil.which(command) or (command if Path(command).is_file() else None)
    if not resolved:
        raise ViewerNotFound(
            f"Could not find the '{command}' viewer on your PATH.\n"
            f"Install Papers, or set {VIEWER_ENV} to another PDF viewer."
        )

    return subprocess.Popen(
        [resolved, target.name],
        cwd=str(target.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def tilde(path: str) -> str:
    """Shorten a path under ``$HOME`` to start with ``~``."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def humanize_time(timestamp: float, now: float | None = None) -> str:
    """Compact, human friendly date: 'just now', '3 h ago', 'Yesterday', 'Mar 4'."""
    if not timestamp:
        return ""
    current = time.time() if now is None else now
    delta = current - timestamp

    if delta < 45:
        return "just now"
    if delta < 3600:
        return f"{max(1, int(delta // 60))} min ago"
    if delta < 6 * 3600:
        return f"{int(delta // 3600)} h ago"

    stamp = time.localtime(timestamp)
    today = time.localtime(current)
    if (stamp.tm_year, stamp.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M", stamp)
    if (stamp.tm_year, stamp.tm_yday) == _yesterday(today):
        return "Yesterday"
    if stamp.tm_year == today.tm_year:
        return time.strftime("%b %d", stamp).replace(" 0", " ")
    return time.strftime("%b %d, %Y", stamp).replace(" 0", " ")


def _yesterday(day: time.struct_time) -> tuple[int, int]:
    previous = time.localtime(time.mktime(day) - 86400)
    return previous.tm_year, previous.tm_yday


def human_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.0f} {unit}" if size >= 10 else f"{size:.1f} {unit}"
        size /= 1024
    return ""  # pragma: no cover


def format_meta(entry) -> str:
    """Right-hand detail line: '1.4 MB · 5 opens', or 'missing'."""
    if not entry.exists:
        return "missing"
    parts = []
    size = human_size(entry.size)
    if size:
        parts.append(size)
    if entry.opens > 1:
        parts.append(f"{entry.opens}× opened")
    return " · ".join(parts)


def open_folder(path: str | os.PathLike[str]) -> None:
    """Ask the desktop to open a directory in the file manager."""
    from gi.repository import Gio

    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=True)
    Gio.AppInfo.launch_default_for_uri(folder.resolve().as_uri(), None)
