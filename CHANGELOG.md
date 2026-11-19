# Changelog

## 0.1.0

- `publish` copies one source file to every target, atomically, and writes
  nothing when a copy was edited since the last publish or a target is
  blocked. `--force` overwrites after a backup, `--dry-run` shows the plan.
- `check` reports each copy as same, stale, missing, edited, linked,
  no-folder or blocked, with exit codes for hooks, cron and CI.
- `diff` shows how edited copies differ from the source.
- `init` writes a config and finds installed tools. `tools` lists the
  built-in locations for Claude Code, Codex CLI, Gemini CLI and opencode.
- Source checks: size limits, UTF-8 and an optional required heading.
- Project mode with `.agents-md-sync.toml`, confined to its own folder.
- Tests on Linux and macOS with Python 3.11–3.14, and a privacy scan of the
  full history in CI.
