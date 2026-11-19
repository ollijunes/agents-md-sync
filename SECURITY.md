# Security

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/ollijunes/agents-md-sync/security/advisories/new).
Do not put your instruction files or paths from your home folder in a public
issue. Describe the problem with synthetic files and include the affected
version.

## What the tool does

- Reads one source file and writes byte-identical copies to the targets
  listed in your config. It writes nowhere else, except its own record and
  backups under `~/.local/state/agents-md-sync/`.
- Writes each copy to a temporary file in the same folder and renames it
  into place, so a tool never reads a half-written instruction file.
- Checks every target before writing anything. If one copy was edited since
  the last publish, or a target is a directory or a symlink to another
  file, nothing is written at all.
- Never writes through a symlink. A symlink that points to the source is
  left alone. Any other symlink blocks the run, also with `--force`.
- Confines a project config (`.agents-md-sync.toml`) to its own folder:
  relative paths only, no built-in tool locations, and no source or target
  outside the folder, also through a symlink. A cloned repository cannot
  make the tool read or write files in your home folder.
- Refuses a source that is empty, cut off, too large, not UTF-8, or that
  does not start with the configured heading. A damaged source cannot
  replace good copies.
- `--force` saves the old copy first, readable only by you (mode 600).
- Keeps the file mode of an existing copy. New copies get mode 644.
- Does not create folders for tools. A tool that is not installed is
  skipped.
- No network access, no subprocesses, no dependencies outside the Python
  standard library.

## What it does not do

- It does not read or judge the text. Instruction files steer what an agent
  does on your machine. Anyone who can change the source file changes what
  every agent is told. Keep the source somewhere only you can write.
- It does not scan for secrets. Do not put keys or passwords in instruction
  files. They are sent to the model provider with every session.
- A copy that is edited in the instant between the check and the write is
  overwritten without a backup. The window is a few milliseconds.
- It does not notice a change by itself. Run `check` from a hook or a
  scheduler if you want to be told.
- It does not protect against someone who can already write to your home
  folder while it runs. Such a person controls your account.

## Repository hygiene

This repository contains no real instruction files. Everything in
`examples/` and the tests is synthetic. CI scans the full Git history with
Gitleaks and with `scripts/check_public_tree.py`, which looks for private
network addresses, home-directory paths, email addresses outside example
domains and private files. Automated scans support a manual review; they do
not prove that nothing private slipped in.
