"""Persistent history storage.

The history is a small JSON document kept under ``$XDG_DATA_HOME/papers-history``.
Writes are atomic and guarded by an advisory ``flock`` so that several running
instances (or the command line) can update it without losing entries.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, TypeVar

SCHEMA_VERSION = 1

#: Hard cap on stored documents; the oldest entry is dropped beyond this.
MAX_ENTRIES = 200

T = TypeVar("T")


def data_dir() -> Path:
    """Return the per-user data directory, honouring ``$XDG_DATA_HOME``."""
    root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / "papers-history"


def default_store_path() -> Path:
    return data_dir() / "history.json"


def normalize(path: str | os.PathLike[str]) -> str:
    """Absolute, symlink-resolved path used as the dedupe key."""
    raw = os.path.abspath(os.fspath(path))
    try:
        return os.path.realpath(raw)
    except OSError:  # pragma: no cover - realpath rarely fails
        return raw


@dataclass
class Entry:
    """One remembered PDF."""

    path: str
    added: float
    last_opened: float
    opens: int = 0
    size: int = 0
    mtime: float = 0.0

    @property
    def title(self) -> str:
        return os.path.basename(self.path)

    @property
    def directory(self) -> str:
        return os.path.dirname(self.path)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    @property
    def activity(self) -> float:
        """Sort timestamp: when the document was last added *or* opened."""
        return max(self.last_opened, self.added)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "added": round(self.added, 3),
            "last_opened": round(self.last_opened, 3),
            "opens": self.opens,
            "size": self.size,
            "mtime": round(self.mtime, 3),
        }

    @classmethod
    def from_dict(cls, raw: object) -> "Entry | None":
        if not isinstance(raw, dict):
            return None
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            return None

        def number(key: str, default: float = 0.0) -> float:
            value = raw.get(key, default)
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        added = number("added")
        last_opened = number("last_opened")
        if not added:
            added = last_opened or time.time()
        return cls(
            path=path,
            added=added,
            last_opened=last_opened,
            opens=int(number("opens")),
            size=int(number("size")),
            mtime=number("mtime"),
        )


def _disk_info(path: str) -> tuple[int, float]:
    try:
        stat = os.stat(path)
        return int(stat.st_size), stat.st_mtime
    except OSError:
        return 0, 0.0


class HistoryStore:
    """Read/write access to the on-disk history."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        max_entries: int = MAX_ENTRIES,
    ) -> None:
        self.path = Path(path).expanduser() if path else default_store_path()
        self.max_entries = max_entries
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    # -- persistence -------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> list[Entry]:
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            return []
        try:
            payload = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            self._quarantine()
            return []

        raw_entries = payload.get("entries") if isinstance(payload, dict) else payload
        if not isinstance(raw_entries, list):
            return []

        entries: list[Entry] = []
        seen: set[str] = set()
        for item in raw_entries:
            entry = Entry.from_dict(item)
            if entry is None:
                continue
            key = normalize(entry.path)
            if key in seen:
                continue
            seen.add(key)
            entry.path = key
            entries.append(entry)
        return entries

    def _write(self, entries: list[Entry]) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "updated": round(time.time(), 3),
            "entries": [entry.to_dict() for entry in entries],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".history-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _quarantine(self) -> None:
        """Move an unreadable history file aside instead of silently losing it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, target)
        except OSError:
            pass

    def _prune(self, entries: list[Entry]) -> list[Entry]:
        if self.max_entries <= 0:
            return []
        entries.sort(key=lambda entry: entry.activity, reverse=True)
        return entries[: self.max_entries]

    def _mutate(self, operation: Callable[[list[Entry]], T]) -> T:
        with self._locked():
            entries = self._read()
            result = operation(entries)
            entries = self._prune(entries)
            self._write(entries)
            return result

    # -- public API --------------------------------------------------------

    def entries(self) -> list[Entry]:
        """All stored documents, most recently active first."""
        entries = self._read()
        entries.sort(key=lambda entry: entry.activity, reverse=True)
        return entries

    def add(
        self,
        path: str | os.PathLike[str],
        *,
        opened: bool = False,
        now: float | None = None,
    ) -> Entry:
        """Insert ``path`` or bump an existing entry. Returns the stored row."""
        timestamp = time.time() if now is None else now
        key = normalize(path)

        def operation(entries: list[Entry]) -> Entry:
            for entry in entries:
                if entry.path == key:
                    entry.size, entry.mtime = _disk_info(key)
                    if opened:
                        entry.last_opened = timestamp
                        entry.opens += 1
                    return entry
            size, mtime = _disk_info(key)
            entry = Entry(
                path=key,
                added=timestamp,
                last_opened=timestamp if opened else 0.0,
                opens=1 if opened else 0,
                size=size,
                mtime=mtime,
            )
            entries.append(entry)
            return entry

        return self._mutate(operation)

    def remove(self, path: str | os.PathLike[str]) -> bool:
        key = normalize(path)

        def operation(entries: list[Entry]) -> bool:
            before = len(entries)
            entries[:] = [entry for entry in entries if entry.path != key]
            return len(entries) != before

        return self._mutate(operation)

    def clear(self) -> None:
        def operation(entries: list[Entry]) -> None:
            entries.clear()

        self._mutate(operation)
