"""Compare the source with its copies and publish it."""

import contextlib
import difflib
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Config

SAME = "same"
LINKED = "linked"
STALE = "stale"
EDITED = "edited"
MISSING = "missing"
NO_FOLDER = "no-folder"
BLOCKED = "blocked"

EXPLAIN = {
    SAME: "identical to the source",
    LINKED: "a symlink to the source",
    STALE: "an older copy; publish updates it",
    EDITED: "changed since the last publish",
    MISSING: "not there yet; publish creates it",
    NO_FOLDER: "skipped, its folder does not exist",
    BLOCKED: "not a regular file",
}


class SourceError(Exception):
    """The source file must not be published as it is."""


@dataclass(frozen=True)
class Item:
    target: Path
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Written:
    target: Path
    backup: Path | None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(config: Config) -> bytes:
    path = config.source
    try:
        if not path.is_file():
            raise SourceError(f"Source file not found: {path}")
        data = path.read_bytes()
    except OSError as error:
        raise SourceError(f"Cannot read the source: {error}") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceError("The source is not UTF-8 text.") from None
    if "\x00" in text:
        raise SourceError("The source contains a NUL byte.")
    if len(data) < config.min_bytes:
        raise SourceError(
            f"The source is {len(data)} bytes, under min_bytes = {config.min_bytes}. "
            "An empty or cut-off file is not published."
        )
    if len(data) > config.max_bytes:
        raise SourceError(
            f"The source is {len(data)} bytes, over max_bytes = {config.max_bytes}. "
            "Some agents cut long instruction files without a warning."
        )
    if config.heading:
        # A byte order mark from a Windows editor is not part of the heading.
        first = text.split("\n", 1)[0].rstrip("\r").removeprefix("\ufeff")
        if first != config.heading:
            raise SourceError("The source does not start with the configured heading.")
    return data


def load_state(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        targets = data["targets"]
        return {str(key): str(value["sha256"]) for key, value in targets.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # An unreadable record only makes the tool more careful: old copies count as edited.
        return {}


def save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"version": 1, "targets": {key: {"sha256": state[key]} for key in sorted(state)}}
    text = json.dumps(payload, indent=2) + "\n"
    _atomic_write(path, text.encode("utf-8"), 0o600)


def inspect(config: Config, source: bytes, state: dict[str, str]) -> list[Item]:
    return [_inspect_one(config, target, source, state) for target in config.targets]


def _inspect_one(config: Config, target: Path, source: bytes, state: dict[str, str]) -> Item:
    if target.is_symlink():
        try:
            if target.resolve(strict=True) == config.source.resolve(strict=True):
                return Item(target, LINKED)
        except OSError:
            pass
        return Item(target, BLOCKED, "a symlink that does not point to the source")
    if not target.parent.is_dir():
        return Item(target, NO_FOLDER)
    if not target.exists():
        return Item(target, MISSING)
    if not target.is_file():
        return Item(target, BLOCKED, "not a regular file")
    try:
        current = target.read_bytes()
    except OSError as error:
        return Item(target, BLOCKED, f"cannot be read: {error.strerror}")
    if current == source:
        return Item(target, SAME)
    if state.get(str(target)) == sha256(current):
        return Item(target, STALE)
    return Item(target, EDITED)


def publish(
    config: Config,
    source: bytes,
    items: list[Item],
    state: dict[str, str],
    backup_dir: Path,
    force: bool = False,
) -> list[Written]:
    """Write the source to every target that needs it. The caller has checked for refusals."""
    written = []
    digest = sha256(source)
    for item in items:
        key = str(item.target)
        if item.status == SAME:
            state[key] = digest
        elif item.status in (STALE, MISSING) or (item.status == EDITED and force):
            backup = _backup(item.target, backup_dir) if item.status == EDITED else None
            mode = _mode(item.target)
            _atomic_write(item.target, source, mode)
            state[key] = digest
            written.append(Written(item.target, backup))
    return written


def unified_diff(source: bytes, target: Path, label: str) -> str:
    try:
        other = target.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        other = ""
    lines = difflib.unified_diff(
        source.decode("utf-8").splitlines(keepends=True),
        other.splitlines(keepends=True),
        fromfile="source",
        tofile=label,
    )
    text = "".join(line if line.endswith("\n") else line + "\n" for line in lines)
    return text


def _mode(target: Path) -> int:
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except OSError:
        return 0o644


def _backup(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    tag = sha256(str(target).encode("utf-8"))[:8]
    backup = backup_dir / f"{stamp}-{tag}-{target.name}"
    _atomic_write(backup, target.read_bytes(), 0o600)
    return backup


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
