import json
import os
import stat

from agents_md_sync import cli
from tests.conftest import SOURCE_TEXT


def test_first_publish_creates_copies(home, capsys):
    home.setup()
    assert home.run("check") == cli.EXIT_OUT_OF_DATE
    assert home.run("publish") == cli.EXIT_OK
    assert home.claude.read_text(encoding="utf-8") == SOURCE_TEXT
    assert home.codex.read_text(encoding="utf-8") == SOURCE_TEXT
    assert stat.S_IMODE(home.claude.stat().st_mode) == 0o644
    assert "2 written, 0 already up to date" in capsys.readouterr().out
    assert home.run("check") == cli.EXIT_OK
    assert "In sync with ~/notes/AGENTS.md." in capsys.readouterr().out


def test_source_change_makes_copies_stale_and_publish_updates(home, capsys):
    home.setup()
    home.run("publish")
    home.source.write_text(SOURCE_TEXT + "Use British spelling.\n", encoding="utf-8")
    capsys.readouterr()
    assert home.run("check") == cli.EXIT_OUT_OF_DATE
    assert "stale: ~/.claude/CLAUDE.md" in capsys.readouterr().out
    assert home.run("publish") == cli.EXIT_OK
    assert "updated: ~/.codex/AGENTS.md" in capsys.readouterr().out
    assert home.codex.read_text(encoding="utf-8").endswith("Use British spelling.\n")


def test_edited_copy_blocks_publish_and_nothing_is_written(home, capsys):
    home.setup()
    home.run("publish")
    home.claude.write_text(SOURCE_TEXT + "- Remember: the user likes tabs.\n", encoding="utf-8")
    home.source.write_text(SOURCE_TEXT + "New rule.\n", encoding="utf-8")
    capsys.readouterr()

    assert home.run("check") == cli.EXIT_EDITED
    assert "edited: ~/.claude/CLAUDE.md" in capsys.readouterr().out
    assert home.run("publish") == cli.EXIT_EDITED
    err = capsys.readouterr().err
    assert "Nothing was written." in err
    assert "the user likes tabs" in home.claude.read_text(encoding="utf-8")
    # The stale Codex copy stays untouched too: a refused publish writes nothing at all.
    assert home.codex.read_text(encoding="utf-8") == SOURCE_TEXT


def test_force_overwrites_after_backup(home, capsys):
    home.setup()
    home.run("publish")
    edited = SOURCE_TEXT + "- A note an agent added.\n"
    home.claude.write_text(edited, encoding="utf-8")
    capsys.readouterr()

    assert home.run("publish", "--force") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "backup of the old copy: ~/state/backups/" in out
    assert home.claude.read_text(encoding="utf-8") == SOURCE_TEXT
    backups = list((home.state.parent / "backups").iterdir())
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == edited
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600


def test_existing_file_without_a_record_counts_as_edited(home):
    home.setup()
    home.claude.write_text("# My old hand-written instructions\n", encoding="utf-8")
    assert home.run("publish") == cli.EXIT_EDITED
    assert home.claude.read_text(encoding="utf-8").startswith("# My old")
    assert not home.codex.exists()


def test_identical_existing_copy_is_adopted(home):
    home.setup()
    home.claude.write_text(SOURCE_TEXT, encoding="utf-8")
    assert home.run("publish") == cli.EXIT_OK
    record = json.loads(home.state.read_text(encoding="utf-8"))
    assert set(record["targets"]) == {str(home.claude), str(home.codex)}
    assert stat.S_IMODE(home.state.stat().st_mode) == 0o600


def test_dry_run_writes_nothing(home, capsys):
    home.setup()
    assert home.run("publish", "--dry-run") == cli.EXIT_OK
    assert "would create: ~/.claude/CLAUDE.md" in capsys.readouterr().out
    assert not home.claude.exists()
    assert not home.state.exists()


def test_dry_run_with_force_names_the_overwrite(home, capsys):
    home.setup()
    home.claude.write_text("old\n", encoding="utf-8")
    assert home.run("publish", "--dry-run", "--force") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "would overwrite (backup first): ~/.claude/CLAUDE.md" in out
    assert home.claude.read_text(encoding="utf-8") == "old\n"


def test_missing_tool_folder_is_skipped(home, capsys):
    home.setup(tools=("claude", "gemini"))
    assert home.run("publish") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "no-folder: ~/.gemini/GEMINI.md" in out
    assert "1 written, 0 already up to date" in out
    assert not (home.root / ".gemini").exists()
    assert home.run("check") == cli.EXIT_OK


def test_existing_mode_is_kept(home):
    home.setup()
    home.run("publish")
    os.chmod(home.claude, 0o600)
    home.source.write_text(SOURCE_TEXT + "More.\n", encoding="utf-8")
    home.run("publish")
    assert stat.S_IMODE(home.claude.stat().st_mode) == 0o600


def test_symlink_to_the_source_is_left_alone(home, capsys):
    home.setup()
    home.claude.symlink_to(home.source)
    assert home.run("publish") == cli.EXIT_OK
    assert home.claude.is_symlink()
    capsys.readouterr()
    assert home.run("check") == cli.EXIT_OK
    assert "linked: ~/.claude/CLAUDE.md" in capsys.readouterr().out


def test_symlink_elsewhere_blocks(home, capsys):
    home.setup()
    other = home.root / "other.md"
    other.write_text("unrelated\n", encoding="utf-8")
    home.claude.symlink_to(other)
    assert home.run("publish", "--force") == cli.EXIT_EDITED
    assert "a symlink that does not point to the source" in capsys.readouterr().err
    assert other.read_text(encoding="utf-8") == "unrelated\n"
    assert not home.codex.exists()


def test_dangling_symlink_blocks(home):
    home.setup()
    home.claude.symlink_to(home.root / "gone.md")
    assert home.run("check") == cli.EXIT_EDITED


def test_directory_as_target_blocks(home, capsys):
    home.setup()
    home.claude.mkdir()
    assert home.run("publish") == cli.EXIT_EDITED
    assert "blocked: ~/.claude/CLAUDE.md (not a regular file)" in capsys.readouterr().err


def test_no_temporary_files_left_behind(home):
    home.setup()
    home.run("publish")
    assert sorted(path.name for path in home.claude.parent.iterdir()) == ["CLAUDE.md"]


def test_corrupt_state_makes_old_copies_edited_not_overwritten(home):
    home.setup()
    home.run("publish")
    home.state.write_text("{not json", encoding="utf-8")
    home.source.write_text(SOURCE_TEXT + "More.\n", encoding="utf-8")
    assert home.run("publish") == cli.EXIT_EDITED
    assert home.claude.read_text(encoding="utf-8") == SOURCE_TEXT


def test_failed_write_keeps_the_record_of_copies_already_written(home, capsys):
    home.setup()
    (home.root / ".codex").chmod(0o500)
    try:
        assert home.run("publish") == cli.EXIT_ERROR
    finally:
        (home.root / ".codex").chmod(0o700)
    assert home.claude.read_text(encoding="utf-8") == SOURCE_TEXT
    assert str(home.claude) in json.loads(home.state.read_text(encoding="utf-8"))["targets"]
    # The source moves on; the copy that was written is stale, not edited.
    home.source.write_text(SOURCE_TEXT + "More.\n", encoding="utf-8")
    capsys.readouterr()
    assert home.run("publish") == cli.EXIT_OK
    assert "updated: ~/.claude/CLAUDE.md" in capsys.readouterr().out


def test_quiet_check_prints_only_problems(home, capsys):
    home.setup()
    home.run("publish")
    capsys.readouterr()
    assert home.run("check", "--quiet") == cli.EXIT_OK
    assert capsys.readouterr().out == ""
    home.codex.write_text("changed\n", encoding="utf-8")
    assert home.run("check", "--quiet") == cli.EXIT_EDITED
    assert (
        capsys.readouterr().out == "edited: ~/.codex/AGENTS.md (changed since the last publish)\n"
    )
