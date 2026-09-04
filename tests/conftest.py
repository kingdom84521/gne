import json
import stat
import subprocess
from pathlib import Path

import pytest

from gne.core import schema


def reset_schema_caches() -> None:
    schema.load_schema.cache_clear()
    schema.note_fields.cache_clear()
    schema.field_by_key.cache_clear()
    schema._note_validator.cache_clear()


@pytest.fixture(autouse=True)
def declared_fields(monkeypatch):
    """測試用的欄位宣告就是套件裡的那份範本。

    gne 不再自帶預設宣告——欄位是專案的事——所以每個測試都得有一份指得到的宣告檔。
    要試「沒有宣告」的那條路，自己把 GNE_SCHEMA 拿掉。

    宣告是讀進來就快取的，換掉宣告檔的測試因此不能把快取留給下一個。
    """
    monkeypatch.setenv(schema.SCHEMA_ENV, str(schema.TEMPLATE_PATH))
    reset_schema_caches()
    yield
    reset_schema_caches()


def repo_root() -> Path:
    """這個 repo 的根。測試不從檔案位置往上數目錄——套件搬家時不該跟著改。"""
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def fake_advisor(tmp_path: Path, body: str) -> str:
    """一支假顧問。真正的顧問就是一支外部指令，所以測試也只需要一支外部指令。"""
    script = tmp_path / "advisor.py"
    script.write_text("#!/usr/bin/env python3\nimport json, sys\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"python3 {script}"


def advisor_replying(tmp_path: Path, reply: object) -> str:
    payload = json.dumps(json.dumps(reply))
    return fake_advisor(tmp_path, f"sys.stdin.read()\nprint({payload})\n")


def write_default_note(git_repo: Path, body: str) -> None:
    """在測試 repo 裡放一份 .gne/default-note。"""
    (git_repo / ".gne").mkdir(exist_ok=True)
    (git_repo / ".gne" / "default-note").write_text(body, encoding="utf-8")


def run_git(*arguments: str, cwd: Path, stdin: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=True, input=stdin
    )
    return completed.stdout.strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """一個獨立的 git repo，沒有 origin——測試絕不會推到共用 remote。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", "-q", "-b", "master", cwd=repo)
    run_git("config", "user.email", "test@example.com", cwd=repo)
    run_git("config", "user.name", "Test User", cwd=repo)
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def origin(git_repo, tmp_path):
    """一個真的 bare origin。取回與推送因此可以真的跑，不必假裝。"""
    remote = tmp_path / "origin.git"
    run_git("init", "-q", "--bare", str(remote), cwd=git_repo)
    run_git("remote", "add", "origin", str(remote), cwd=git_repo)
    return remote


@pytest.fixture
def commit(git_repo):
    """在 git_repo 裡建一個 commit，回傳其完整 hash。"""
    counter = {"value": 0}

    def make(subject: str = "feat: something", author: str | None = None) -> str:
        counter["value"] += 1
        (git_repo / f"file{counter['value']}.txt").write_text(str(counter["value"]))
        run_git("add", "-A", cwd=git_repo)
        arguments = ["commit", "-q", "-m", subject]
        if author is not None:
            arguments += ["--author", author]
        run_git(*arguments, cwd=git_repo)
        return run_git("rev-parse", "HEAD", cwd=git_repo)

    return make


@pytest.fixture
def notes_tree(git_repo):
    """直接鋪一棵 notes 樹，好掛備註到本地沒有的物件上。

    從 origin 取回的 refs/notes 就會有這種項目：備註在，被標註的 commit 不在。
    """

    def build(entries: dict[str, str]) -> None:
        lines = []
        for target, body in entries.items():
            blob = run_git("hash-object", "-w", "--stdin", cwd=git_repo, stdin=body)
            lines.append(f"100644 blob {blob}\t{target}")
        tree = run_git("mktree", cwd=git_repo, stdin="\n".join(lines) + "\n")
        commit = run_git("commit-tree", tree, "-m", "notes", cwd=git_repo)
        run_git("update-ref", "refs/notes/commits", commit, cwd=git_repo)

    return build
