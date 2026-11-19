# Contributing

Bug fixes and corrections are welcome. A new feature should keep the tool
small: one source, identical copies, a clear answer about drift.

```sh
uv sync --locked
uv run python -m pytest --cov=agents_md_sync --cov-fail-under=90
uv run ruff check .
uv run ruff format --check .
gitleaks git --redact --no-banner .
python3 scripts/check_public_tree.py
```

## Rules

- Never commit a real instruction file or a path from your own machine, not
  even in a temporary commit. Build what a test needs in `tmp_path`.
- Tests must not read the real home folder. Pass `--home` and `--state`, as
  the fixture in `tests/conftest.py` does.
- Keep the runtime on the Python standard library.
- A new built-in tool location needs a source: link the tool's own
  documentation for the file in the pull request. Blog posts and other
  people's dotfiles are not enough.
- Do not weaken the checks that stop a publish (edited copies, symlinks,
  source size and heading) to make something work. Explain the problem in
  an issue instead.

Use a public-safe Git author address. Report vulnerabilities through
[SECURITY.md](SECURITY.md), not a public issue.
