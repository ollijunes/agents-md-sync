"""Config file, tool presets and path handling."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_CONFIG = ".agents-md-sync.toml"
DEFAULT_MIN_BYTES = 1
# Codex stops reading instruction files at 32 KiB by default and truncates without a warning.
DEFAULT_MAX_BYTES = 32768


class ConfigError(Exception):
    """A problem the user can fix in the config file or on the command line."""


@dataclass(frozen=True)
class Preset:
    name: str
    tool: str
    folder_env: str | None
    folder: str
    filename: str

    def target(self, home: Path, env: dict[str, str]) -> Path:
        override = env.get(self.folder_env, "") if self.folder_env else ""
        folder = expand(override, home) if override else home / self.folder
        return folder / self.filename


# Only locations documented by the tool's own vendor. Anything else is a plain path.
PRESETS = {
    preset.name: preset
    for preset in (
        Preset("claude", "Claude Code", "CLAUDE_CONFIG_DIR", ".claude", "CLAUDE.md"),
        Preset("codex", "Codex CLI", "CODEX_HOME", ".codex", "AGENTS.md"),
        Preset("gemini", "Gemini CLI", None, ".gemini", "GEMINI.md"),
        Preset("opencode", "opencode", None, ".config/opencode", "AGENTS.md"),
    )
}


@dataclass(frozen=True)
class Config:
    path: Path
    source: Path
    targets: tuple[Path, ...]
    min_bytes: int = DEFAULT_MIN_BYTES
    max_bytes: int = DEFAULT_MAX_BYTES
    heading: str = ""
    labels: dict[Path, str] = field(default_factory=dict)

    def label(self, target: Path) -> str:
        return self.labels.get(target, str(target))


def expand(value: str, home: Path, base: Path | None = None) -> Path:
    """Expand a leading ~ against the given home and resolve relative paths against base."""
    if value == "~":
        path = home
    elif value.startswith("~/"):
        path = home / value[2:]
    else:
        path = Path(value)
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return Path(os.path.normpath(path))


def default_config_path(home: Path, env: dict[str, str]) -> Path:
    base = env.get("XDG_CONFIG_HOME", "")
    folder = expand(base, home) if base else home / ".config"
    return folder / "agents-md-sync" / "config.toml"


def default_state_path(home: Path, env: dict[str, str]) -> Path:
    base = env.get("XDG_STATE_HOME", "")
    folder = expand(base, home) if base else home / ".local" / "state"
    return folder / "agents-md-sync" / "state.json"


def load(path: Path, home: Path, env: dict[str, str]) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"No config at {path}. Run `agents-md-sync init --source FILE` first."
        ) from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from None

    unknown = sorted(
        set(data) - {"source", "targets", "tools", "min_bytes", "max_bytes", "heading"}
    )
    if unknown:
        raise ConfigError(f"Unknown config keys: {', '.join(unknown)}")

    source = data.get("source")
    if not isinstance(source, str) or not source:
        raise ConfigError("`source` must be the path of your instruction file.")
    base = path.parent
    source_path = expand(source, home, base)

    tools = _string_list(data, "tools")
    paths = _string_list(data, "targets")
    targets: list[Path] = []
    labels: dict[Path, str] = {}
    for name in tools:
        preset = PRESETS.get(name)
        if preset is None:
            known = ", ".join(sorted(PRESETS))
            raise ConfigError(
                f"Unknown tool `{name}`. Known tools: {known}. Use `targets` for others."
            )
        target = preset.target(home, env)
        targets.append(target)
        labels[target] = f"{preset.name}: {target}"
    for value in paths:
        targets.append(expand(value, home, base))
    if not targets:
        raise ConfigError("Nothing to sync: list at least one entry in `tools` or `targets`.")
    if len(set(targets)) != len(targets):
        raise ConfigError("The same target is listed twice.")
    if source_path in targets:
        raise ConfigError("The source file is also listed as a target.")
    if path.name == PROJECT_CONFIG:
        _confine(path.parent, source, tools, paths, [source_path, *targets])

    min_bytes = _size(data, "min_bytes", DEFAULT_MIN_BYTES)
    max_bytes = _size(data, "max_bytes", DEFAULT_MAX_BYTES)
    if min_bytes > max_bytes:
        raise ConfigError("`min_bytes` is larger than `max_bytes`.")
    heading = data.get("heading", "")
    if not isinstance(heading, str):
        raise ConfigError("`heading` must be a string.")

    return Config(
        path=path,
        source=source_path,
        targets=tuple(targets),
        min_bytes=min_bytes,
        max_bytes=max_bytes,
        heading=heading,
        labels=labels,
    )


def render(source: str, tools: list[str], targets: list[str]) -> str:
    """Text of a new config file."""
    lines = [
        "# agents-md-sync: one instruction file, copied to every coding agent.",
        "# Edit the source file, then run `agents-md-sync publish`.",
        "",
        f"source = {_quote(source)}",
        "",
        "# Tools with a documented location: claude, codex, gemini, opencode.",
        f"tools = [{', '.join(_quote(name) for name in tools)}]",
        "",
        "# Any other file that should be a copy. Relative paths start at this file's folder.",
        f"targets = [{', '.join(_quote(path) for path in targets)}]",
        "",
        "# Refuse to publish a source outside these sizes. Codex reads 32 KiB at most.",
        f"min_bytes = {DEFAULT_MIN_BYTES}",
        f"max_bytes = {DEFAULT_MAX_BYTES}",
        "",
        "# Optional: the source must start with this line, so a wrong file is never published.",
        'heading = ""',
        "",
    ]
    return "\n".join(lines)


def _confine(
    root: Path, source: str, tools: list[str], values: list[str], resolved: list[Path]
) -> None:
    """A project config may come from a repository someone else wrote.

    It can only read and write inside its own folder, so opening a cloned repository
    and running publish there cannot replace an instruction file in the home folder.
    """
    if tools:
        raise ConfigError(
            f"`tools` is not allowed in {PROJECT_CONFIG}. "
            "A project config can only write inside its own folder."
        )
    for value in [source, *values]:
        if value.startswith("~") or Path(value).is_absolute():
            raise ConfigError(
                f"{PROJECT_CONFIG} takes relative paths only, and `{value}` is not one."
            )
    real_root = Path(os.path.realpath(root))
    for index, path in enumerate(resolved):
        if index == 0:
            # The source is read through symlinks, so it is resolved all the way.
            real = Path(os.path.realpath(path))
        else:
            # A target is never written through a symlink, so its folder decides.
            real = Path(os.path.realpath(path.parent)) / path.name
        if real_root != real and real_root not in real.parents:
            raise ConfigError(
                f"{PROJECT_CONFIG} points outside its own folder: {path.name}. "
                "A project config can only write inside its own folder."
            )


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _string_list(data: dict, key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"`{key}` must be a list of strings.")
    return value


def _size(data: dict, key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"`{key}` must be a whole number of bytes.")
    return value
