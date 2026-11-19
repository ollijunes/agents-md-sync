"""Command line interface."""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, config, core

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_OUT_OF_DATE = 3
EXIT_EDITED = 4

PROJECT_CONFIG = config.PROJECT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents-md-sync",
        description="Keep one instruction file in sync across coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"agents-md-sync {__version__}")
    parser.add_argument("--config", help="config file (default: ./.agents-md-sync.toml, then user)")
    parser.add_argument("--state", help="file that records what was published")
    parser.add_argument("--home", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write a config file")
    init.add_argument("--source", required=True, help="the one file you edit")
    init.add_argument("--tool", action="append", default=[], choices=sorted(config.PRESETS))
    init.add_argument(
        "--target", action="append", default=[], help="any other file to keep as a copy"
    )
    init.add_argument("--project", action="store_true", help=f"write ./{PROJECT_CONFIG} instead")

    check = sub.add_parser("check", help="compare the copies with the source, change nothing")
    check.add_argument("--quiet", action="store_true", help="print only copies that differ")

    publish = sub.add_parser("publish", help="copy the source to every target")
    publish.add_argument("--dry-run", action="store_true", help="show what would be written")
    publish.add_argument(
        "--force", action="store_true", help="overwrite edited copies, after a backup of each"
    )

    diff = sub.add_parser("diff", help="show how the copies differ from the source")
    diff.add_argument(
        "target", nargs="?", help="a tool name or path; default: every differing copy"
    )

    sub.add_parser("tools", help="list the built-in tool locations")
    return parser


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ) if env is None else env
    home = Path(args.home) if args.home else Path(env.get("HOME") or Path.home())
    home = Path(os.path.abspath(home))
    try:
        return _run(args, home, env)
    except (config.ConfigError, core.SourceError) as error:
        print(f"agents-md-sync: {error}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as error:
        print(f"agents-md-sync: {error.strerror}: {error.filename}", file=sys.stderr)
        return EXIT_ERROR


def _run(args: argparse.Namespace, home: Path, env: dict[str, str]) -> int:
    if args.command == "tools":
        for preset in config.PRESETS.values():
            target = preset.target(home, env)
            found = "found" if target.parent.is_dir() else "folder not found"
            print(f"{preset.name:<9} {preset.tool:<12} {_short(target, home)} ({found})")
        return EXIT_OK
    if args.command == "init":
        return _init(args, home, env)

    cfg = config.load(_config_path(args, home, env), home, env)
    state_path = Path(args.state) if args.state else config.default_state_path(home, env)
    source = core.read_source(cfg)
    state = core.load_state(state_path)
    items = core.inspect(cfg, source, state)

    if args.command == "check":
        return _check(cfg, items, home, args.quiet)
    if args.command == "diff":
        return _diff(cfg, source, items, home, args.target, env)
    return _publish(args, cfg, source, items, state, state_path, home)


def _config_path(args: argparse.Namespace, home: Path, env: dict[str, str]) -> Path:
    if args.config:
        return Path(os.path.abspath(args.config))
    if env.get("AGENTS_MD_SYNC_CONFIG"):
        return Path(os.path.abspath(env["AGENTS_MD_SYNC_CONFIG"]))
    project = Path.cwd() / PROJECT_CONFIG
    if project.is_file():
        return project
    return config.default_config_path(home, env)


def _init(args: argparse.Namespace, home: Path, env: dict[str, str]) -> int:
    if args.config:
        path = Path(os.path.abspath(args.config))
    elif args.project:
        path = Path.cwd() / PROJECT_CONFIG
    else:
        path = config.default_config_path(home, env)
    if path.exists():
        raise config.ConfigError(f"{_short(path, home)} already exists. Edit it instead.")
    project = path.name == PROJECT_CONFIG
    tools = list(dict.fromkeys(args.tool))
    if project and tools:
        raise config.ConfigError(
            f"{PROJECT_CONFIG} cannot use --tool. Give the files in the project with --target."
        )
    if not tools and not args.target and not project:
        tools = [
            preset.name
            for preset in config.PRESETS.values()
            if preset.target(home, env).parent.is_dir()
        ]
    if not tools and not args.target:
        if project:
            raise config.ConfigError(
                f"{PROJECT_CONFIG} needs the copies: give each with --target, e.g. CLAUDE.md."
            )
        raise config.ConfigError(
            "Found no known tool folder. Name one with --tool or give a path with --target."
        )

    def place(value: str) -> str:
        # Paths on the command line are relative to the current folder. A project config
        # stores them relative to itself; a user config stores them absolute.
        absolute = config.expand(value, home)
        if project:
            return os.path.relpath(absolute, path.parent)
        return _short(absolute, home)

    text = config.render(place(args.source), tools, [place(value) for value in args.target])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        cfg = config.load(path, home, env)
    except config.ConfigError:
        path.unlink()
        raise
    print(f"Wrote {_short(path, home)}")
    for target in cfg.targets:
        print(f"  target: {_short(target, home)}")
    print("Next: agents-md-sync check")
    return EXIT_OK


def _check(cfg: config.Config, items: list[core.Item], home: Path, quiet: bool) -> int:
    for item in items:
        if quiet and item.status in (core.SAME, core.LINKED, core.NO_FOLDER):
            continue
        print(_line(item, home))
    statuses = {item.status for item in items}
    if statuses & {core.EDITED, core.BLOCKED}:
        if not quiet:
            print("A copy was changed by hand or by an agent. Run `agents-md-sync diff`.")
        return EXIT_EDITED
    if statuses & {core.STALE, core.MISSING}:
        if not quiet:
            print("Run `agents-md-sync publish`.")
        return EXIT_OUT_OF_DATE
    if not quiet:
        print(f"In sync with {_short(cfg.source, home)}.")
    return EXIT_OK


def _diff(
    cfg: config.Config,
    source: bytes,
    items: list[core.Item],
    home: Path,
    wanted: str | None,
    env: dict[str, str],
) -> int:
    if wanted:
        if wanted in config.PRESETS:
            path = config.PRESETS[wanted].target(home, env)
        else:
            path = config.expand(wanted, home)
        items = [item for item in items if item.target == path]
        if not items:
            raise config.ConfigError(f"{wanted} is not a target in the config.")
    shown = 0
    for item in items:
        # Without a named target, show only what publish would refuse to overwrite.
        if item.status == core.EDITED or (wanted and item.status == core.STALE):
            sys.stdout.write(core.unified_diff(source, item.target, _short(item.target, home)))
            shown += 1
    if not shown:
        print("No differing copy." if wanted else "No edited copies.")
    return EXIT_OK


def _publish(
    args: argparse.Namespace,
    cfg: config.Config,
    source: bytes,
    items: list[core.Item],
    state: dict[str, str],
    state_path: Path,
    home: Path,
) -> int:
    blocked = [item for item in items if item.status == core.BLOCKED]
    edited = [item for item in items if item.status == core.EDITED]
    if blocked or (edited and not args.force):
        for item in blocked + ([] if args.force else edited):
            print(_line(item, home), file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        if blocked:
            print("Replace the blocked target with a regular file, or remove it.", file=sys.stderr)
        if edited and not args.force:
            print(
                "Move the changes you want into the source (`agents-md-sync diff`), "
                "then publish again. `--force` overwrites after a backup.",
                file=sys.stderr,
            )
        return EXIT_EDITED

    if args.dry_run:
        for item in items:
            action = {
                core.STALE: "would update",
                core.MISSING: "would create",
                core.EDITED: "would overwrite (backup first)",
            }.get(item.status)
            print(f"{action}: {_short(item.target, home)}" if action else _line(item, home))
        return EXIT_OK

    try:
        written = core.publish(cfg, source, items, state, state_path.parent / "backups", args.force)
    finally:
        # Also after a failed write: the copies written so far must stay on record.
        core.save_state(state_path, state)
    done = {entry.target: entry for entry in written}
    for item in items:
        entry = done.get(item.target)
        if entry is None:
            if item.status == core.NO_FOLDER:
                print(_line(item, home))
            continue
        verb = "created" if item.status == core.MISSING else "updated"
        print(f"{verb}: {_short(item.target, home)}")
        if entry.backup:
            print(f"  backup of the old copy: {_short(entry.backup, home)}")
    total = sum(item.status != core.NO_FOLDER for item in items)
    print(
        f"{len(written)} written, {total - len(written)} already up to date ({len(source)} bytes)."
    )
    return EXIT_OK


def _line(item: core.Item, home: Path) -> str:
    detail = item.detail or core.EXPLAIN[item.status]
    return f"{item.status}: {_short(item.target, home)} ({detail})"


def _short(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)
