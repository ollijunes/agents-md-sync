import pytest

from agents_md_sync import cli

SOURCE_TEXT = "# Shared instructions\n\nAnswer briefly. Run the tests before you say done.\n"


class Home:
    """A synthetic home folder. Nothing here reads the real one."""

    def __init__(self, root):
        self.root = root
        self.env = {"HOME": str(root)}
        self.source = root / "notes" / "AGENTS.md"
        self.state = root / "state" / "state.json"
        self.config = root / ".config" / "agents-md-sync" / "config.toml"
        self.claude = root / ".claude" / "CLAUDE.md"
        self.codex = root / ".codex" / "AGENTS.md"

    def setup(self, tools=("claude", "codex"), targets=(), extra=""):
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text(SOURCE_TEXT, encoding="utf-8")
        for name in (".claude", ".codex"):
            (self.root / name).mkdir(exist_ok=True)
        self.config.parent.mkdir(parents=True, exist_ok=True)
        tool_list = ", ".join(f'"{name}"' for name in tools)
        target_list = ", ".join(f'"{path}"' for path in targets)
        lines = ['source = "~/notes/AGENTS.md"', f"tools = [{tool_list}]"]
        lines.append(f"targets = [{target_list}]")
        self.config.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
        return self

    def run(self, *argv, env=None):
        base = ["--home", str(self.root), "--state", str(self.state)]
        return cli.main([*base, *argv], env={**self.env, **(env or {})})


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Home(tmp_path)
