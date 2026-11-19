import pytest

from agents_md_sync import cli, config
from tests.conftest import SOURCE_TEXT


def test_init_detects_installed_tools(home, capsys):
    (home.root / ".claude").mkdir()
    (home.root / ".config" / "opencode").mkdir(parents=True)
    assert home.run("init", "--source", "~/notes/AGENTS.md") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Wrote ~/.config/agents-md-sync/config.toml" in out
    assert "target: ~/.claude/CLAUDE.md" in out
    assert "target: ~/.config/opencode/AGENTS.md" in out
    cfg = config.load(home.config, home.root, home.env)
    assert cfg.source == home.source
    assert [path.name for path in cfg.targets] == ["CLAUDE.md", "AGENTS.md"]


def test_init_with_named_tools_and_targets(home):
    assert (
        home.run("init", "--source", "~/a.md", "--tool", "codex", "--target", "~/x/RULES.md")
        == cli.EXIT_OK
    )
    cfg = config.load(home.config, home.root, home.env)
    assert cfg.targets == (home.codex, home.root / "x" / "RULES.md")


def test_init_refuses_to_overwrite(home, capsys):
    home.setup()
    assert home.run("init", "--source", "~/a.md", "--tool", "codex") == cli.EXIT_ERROR
    assert "already exists" in capsys.readouterr().err


def test_init_without_any_tool_folder(home, capsys):
    assert home.run("init", "--source", "~/a.md") == cli.EXIT_ERROR
    assert "Found no known tool folder" in capsys.readouterr().err


def test_project_config_keeps_copies_next_to_it(home, monkeypatch, capsys):
    repo = home.root / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(SOURCE_TEXT, encoding="utf-8")
    # Paths on the command line are relative to the current folder, not to the config file.
    assert (
        home.run(
            "--config",
            str(repo / ".agents-md-sync.toml"),
            "init",
            "--source",
            "repo/AGENTS.md",
            "--target",
            "repo/CLAUDE.md",
            "--target",
            "repo/.github/copilot-instructions.md",
        )
        == cli.EXIT_OK
    )
    stored = (repo / ".agents-md-sync.toml").read_text(encoding="utf-8")
    assert 'source = "AGENTS.md"' in stored
    assert '"CLAUDE.md", ".github/copilot-instructions.md"' in stored
    (repo / ".github").mkdir()
    assert home.run("--config", str(repo / ".agents-md-sync.toml"), "publish") == cli.EXIT_OK
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == SOURCE_TEXT
    assert (repo / ".github" / "copilot-instructions.md").read_text(encoding="utf-8") == SOURCE_TEXT


def test_project_config_in_the_current_folder_wins(home, monkeypatch, capsys):
    home.setup()
    repo = home.root / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(SOURCE_TEXT, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert home.run("init", "--project", "--source", "AGENTS.md", "--target", "GEMINI.md") == 0
    capsys.readouterr()
    assert home.run("publish") == cli.EXIT_OK
    assert (repo / "GEMINI.md").exists()
    assert not home.claude.exists()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('source = "AGENTS.md"\ntargets = ["~/.claude/CLAUDE.md"]\n', "relative paths only"),
        ('source = "AGENTS.md"\ntargets = ["/tmp/x.md"]\n', "relative paths only"),
        ('source = "~/notes/AGENTS.md"\ntargets = ["CLAUDE.md"]\n', "relative paths only"),
        ('source = "AGENTS.md"\ntargets = ["../outside.md"]\n', "outside its own folder"),
        ('source = "../AGENTS.md"\ntargets = ["CLAUDE.md"]\n', "outside its own folder"),
        ('source = "AGENTS.md"\ntargets = ["link/CLAUDE.md"]\n', "outside its own folder"),
        ('source = "leak.md"\ntargets = ["CLAUDE.md"]\n', "outside its own folder"),
        ('source = "AGENTS.md"\ntools = ["claude"]\n', "`tools` is not allowed"),
    ],
)
def test_project_config_cannot_reach_outside_its_folder(home, monkeypatch, capsys, body, message):
    """A cloned repository must not be able to replace files in the home folder."""
    (home.root / ".claude").mkdir()
    (home.root / "private.md").write_text("private\n", encoding="utf-8")
    repo = home.root / "cloned"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Planted instructions\n", encoding="utf-8")
    (repo / "link").symlink_to(home.root / ".claude", target_is_directory=True)
    (repo / "leak.md").symlink_to(home.root / "private.md")
    (repo / ".agents-md-sync.toml").write_text(body, encoding="utf-8")
    monkeypatch.chdir(repo)
    for command in ("publish", "check", "diff"):
        assert home.run(command) == cli.EXIT_ERROR
        assert message in capsys.readouterr().err
    assert not home.claude.exists()
    assert not (home.root / "outside.md").exists()
    assert not (repo / "CLAUDE.md").exists()


def test_project_config_is_confined_also_when_named_explicitly(home, capsys):
    repo = home.root / "cloned"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Planted instructions\n", encoding="utf-8")
    path = repo / ".agents-md-sync.toml"
    path.write_text('source = "AGENTS.md"\ntargets = ["../x.md"]\n', encoding="utf-8")
    assert home.run("--config", str(path), "publish") == cli.EXIT_ERROR
    assert home.run("publish", env={"AGENTS_MD_SYNC_CONFIG": str(path)}) == cli.EXIT_ERROR
    assert not (home.root / "x.md").exists()


def test_init_stores_relative_paths_as_absolute_in_the_user_config(home, monkeypatch):
    work = home.root / "work"
    work.mkdir()
    (work / "AGENTS.md").write_text(SOURCE_TEXT, encoding="utf-8")
    (home.root / ".codex").mkdir()
    monkeypatch.chdir(work)
    assert home.run("init", "--source", "AGENTS.md", "--target", "../copy.md") == cli.EXIT_OK
    stored = home.config.read_text(encoding="utf-8")
    assert 'source = "~/work/AGENTS.md"' in stored
    assert 'targets = ["~/copy.md"]' in stored
    cfg = config.load(home.config, home.root, home.env)
    assert cfg.source == work / "AGENTS.md"
    assert home.run("publish") == cli.EXIT_OK
    assert (home.root / "copy.md").read_text(encoding="utf-8") == SOURCE_TEXT


def test_init_project_does_not_add_tools(home, monkeypatch, capsys):
    (home.root / ".claude").mkdir()
    repo = home.root / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(SOURCE_TEXT, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert home.run("init", "--project", "--source", "AGENTS.md") == cli.EXIT_ERROR
    assert "needs the copies: give each with --target" in capsys.readouterr().err
    assert not (repo / ".agents-md-sync.toml").exists()
    assert home.run("init", "--project", "--source", "AGENTS.md", "--tool", "claude") == 1
    assert "cannot use --tool" in capsys.readouterr().err
    assert not (repo / ".agents-md-sync.toml").exists()


def test_init_removes_a_config_that_does_not_load(home, monkeypatch, capsys):
    repo = home.root / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    outside = home.root / "outside.md"
    assert home.run("init", "--project", "--source", "AGENTS.md", "--target", str(outside)) == 1
    assert "outside its own folder" in capsys.readouterr().err
    assert not (repo / ".agents-md-sync.toml").exists()


def test_config_from_environment(home):
    home.setup()
    other = home.root / "other.toml"
    other.write_text('source = "~/notes/AGENTS.md"\ntargets = ["~/copy.md"]\n', encoding="utf-8")
    assert home.run("publish", env={"AGENTS_MD_SYNC_CONFIG": str(other)}) == cli.EXIT_OK
    assert (home.root / "copy.md").exists()
    assert not home.claude.exists()


def test_tool_folder_overrides_from_environment(home):
    home.setup(tools=("claude", "codex"))
    for name in ("claude-alt", "codex-alt"):
        (home.root / name).mkdir()
    env = {"CLAUDE_CONFIG_DIR": "~/claude-alt", "CODEX_HOME": str(home.root / "codex-alt")}
    assert home.run("publish", env=env) == cli.EXIT_OK
    assert (home.root / "claude-alt" / "CLAUDE.md").exists()
    assert (home.root / "codex-alt" / "AGENTS.md").exists()
    assert not home.claude.exists()


def test_xdg_folders_are_honoured(home):
    env = {"HOME": str(home.root), "XDG_CONFIG_HOME": "~/cfg", "XDG_STATE_HOME": "~/st"}
    assert config.default_config_path(home.root, env) == (
        home.root / "cfg" / "agents-md-sync" / "config.toml"
    )
    assert config.default_state_path(home.root, env) == (
        home.root / "st" / "agents-md-sync" / "state.json"
    )


def test_default_state_location_is_used_without_the_option(home):
    home.setup()
    assert cli.main(["--home", str(home.root), "publish"], env=home.env) == cli.EXIT_OK
    assert (home.root / ".local" / "state" / "agents-md-sync" / "state.json").is_file()


def test_tools_lists_presets(home, capsys):
    (home.root / ".codex").mkdir()
    assert home.run("tools") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "codex     Codex CLI    ~/.codex/AGENTS.md (found)" in out
    assert "gemini    Gemini CLI   ~/.gemini/GEMINI.md (folder not found)" in out


def test_diff_shows_the_edit(home, capsys):
    home.setup()
    home.run("publish")
    home.claude.write_text(SOURCE_TEXT + "- Added by an agent.\n", encoding="utf-8")
    capsys.readouterr()
    assert home.run("diff") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "--- source" in out
    assert "+++ ~/.claude/CLAUDE.md" in out
    assert "+- Added by an agent." in out
    assert home.run("diff", "codex") == cli.EXIT_OK
    assert capsys.readouterr().out == "No differing copy.\n"
    assert home.run("diff", "~/.claude/CLAUDE.md") == cli.EXIT_OK
    assert "+- Added by an agent." in capsys.readouterr().out


def test_diff_skips_stale_copies_unless_named(home, capsys):
    home.setup()
    home.run("publish")
    home.source.write_text(SOURCE_TEXT + "New rule.\n", encoding="utf-8")
    capsys.readouterr()
    assert home.run("diff") == cli.EXIT_OK
    assert capsys.readouterr().out == "No edited copies.\n"
    assert home.run("diff", "claude") == cli.EXIT_OK
    assert "-New rule." in capsys.readouterr().out


def test_diff_ends_with_a_newline_when_the_copy_does_not(home, capsys):
    home.setup()
    home.run("publish")
    home.claude.write_text("no newline at the end", encoding="utf-8")
    capsys.readouterr()
    home.run("diff")
    assert capsys.readouterr().out.endswith("+no newline at the end\n")


def test_diff_of_unknown_target(home, capsys):
    home.setup()
    assert home.run("diff", "~/nope.md") == cli.EXIT_ERROR
    assert "is not a target in the config" in capsys.readouterr().err


def test_missing_config(home, capsys):
    assert home.run("check") == cli.EXIT_ERROR
    assert "Run `agents-md-sync init --source FILE` first." in capsys.readouterr().err


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("source = 1\n", "`source` must be the path"),
        ('source = "a.md"\n', "Nothing to sync"),
        ('source = "a.md"\ntools = ["cursor"]\n', "Unknown tool `cursor`"),
        ('source = "a.md"\ntargets = "b.md"\n', "`targets` must be a list of strings"),
        ('source = "a.md"\ntargets = ["b.md", "b.md"]\n', "listed twice"),
        ('source = "a.md"\ntargets = ["a.md"]\n', "also listed as a target"),
        ('source = "a.md"\ntargets = ["b.md"]\nmax_bytes = "big"\n', "whole number of bytes"),
        ('source = "a.md"\ntargets = ["b.md"]\nmin_bytes = 9\nmax_bytes = 2\n', "larger than"),
        ('source = "a.md"\ntargets = ["b.md"]\nheading = 3\n', "`heading` must be a string"),
        ('source = "a.md"\ntargets = ["b.md"]\ncolour = "red"\n', "Unknown config keys: colour"),
        ("source = [\n", "Cannot read"),
    ],
)
def test_config_errors(home, capsys, body, message):
    home.config.parent.mkdir(parents=True)
    home.config.write_text(body, encoding="utf-8")
    assert home.run("check") == cli.EXIT_ERROR
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "extra", "message"),
    [
        (b"", "min_bytes = 10\n", "under min_bytes = 10"),
        (b"x" * 50, "max_bytes = 20\n", "over max_bytes = 20"),
        (b"# Wrong file\n", 'heading = "# Shared instructions"\n', "configured heading"),
        (b"\xff\xfe not utf-8", "", "not UTF-8 text"),
        (b"a\x00b", "", "NUL byte"),
    ],
)
def test_bad_source_is_never_published(home, capsys, content, extra, message):
    home.setup(extra=extra)
    home.source.write_bytes(content)
    assert home.run("publish") == cli.EXIT_ERROR
    assert message in capsys.readouterr().err
    assert not home.claude.exists()


def test_heading_accepts_the_right_file_with_crlf(home):
    home.setup(extra='heading = "# Shared instructions"\n')
    home.source.write_bytes(b"# Shared instructions\r\n\r\nText.\r\n")
    assert home.run("publish") == cli.EXIT_OK
    assert home.claude.read_bytes() == b"# Shared instructions\r\n\r\nText.\r\n"


def test_heading_ignores_a_byte_order_mark(home):
    home.setup(extra='heading = "# Shared instructions"\n')
    home.source.write_bytes("\ufeff# Shared instructions\n\nText.\n".encode())
    assert home.run("publish") == cli.EXIT_OK


def test_missing_source(home, capsys):
    home.setup()
    home.source.unlink()
    assert home.run("check") == cli.EXIT_ERROR
    assert "Source file not found" in capsys.readouterr().err


def test_unwritable_target_folder_reports_an_error(home, capsys):
    home.setup(tools=("claude",))
    (home.root / ".claude").chmod(0o500)
    try:
        assert home.run("publish") == cli.EXIT_ERROR
    finally:
        (home.root / ".claude").chmod(0o700)
    assert "agents-md-sync:" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("agents-md-sync 0.")


def test_module_entry_point(home):
    import subprocess
    import sys

    home.setup()
    result = subprocess.run(
        [sys.executable, "-m", "agents_md_sync", "--home", str(home.root), "tools"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "claude" in result.stdout
