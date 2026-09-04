"""pre-push hook 與工具講的是同一條規則。

hook 是純 bash 的最後防線，所以記號的名字在那裡有第二份。改名時這組測試會失敗，
兩邊因此不會各說各話。
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import repo_root
from gne.core import provenance

HOOK_PATH = repo_root() / ".githooks" / "pre-push"

EMPTY_SHA = "0" * 40


@pytest.fixture
def hook_source():
    return HOOK_PATH.read_text(encoding="utf-8")


def test_the_hook_is_installed_where_core_hookspath_points():
    assert HOOK_PATH.is_file()


def test_the_hook_is_executable():
    assert stat.S_IMODE(HOOK_PATH.stat().st_mode) & stat.S_IXUSR


def test_the_hook_looks_for_the_key_the_tool_actually_writes(hook_source):
    assert f"marker={provenance.AI_GENERATED_KEY}" in hook_source


def run_hook(repo: Path, local_sha: str, remote_ref: str = "refs/notes/commits"):
    return subprocess.run(
        [str(HOOK_PATH)],
        cwd=repo,
        input=f"{remote_ref} {local_sha} {remote_ref} {EMPTY_SHA}\n",
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": str(repo / ".git")},
    )


@pytest.fixture
def noted(git_repo, commit):
    def attach(body: str) -> str:
        revision = commit()
        subprocess.run(
            ["git", "notes", "add", "-f", "-m", body, revision], cwd=git_repo, check=True
        )
        return revision

    return attach


def notes_ref_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "refs/notes/commits"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_a_reviewed_note_may_be_pushed(git_repo, noted):
    noted("type: fix\nchange_log: 人看過了")
    assert run_hook(git_repo, notes_ref_sha(git_repo)).returncode == 0


def test_a_note_still_carrying_the_marker_is_refused(git_repo, noted):
    revision = noted("type: fix\nai_generated:\n  at: '2026-09-01T16:20:00+08:00'\n  fields:\n  - type")
    completed = run_hook(git_repo, notes_ref_sha(git_repo))
    assert completed.returncode == 1
    assert revision[:10] in completed.stderr
    assert "gne --ai-generated" in completed.stderr


def test_the_refusal_names_the_commit_subject(git_repo, noted):
    noted("type: fix\nai_generated: {fields: [type]}")
    assert "feat: something" in run_hook(git_repo, notes_ref_sha(git_repo)).stderr


def test_a_nested_key_of_the_same_name_is_not_a_marker(git_repo, noted):
    """記號是頂層鍵。欄位內容裡出現同名的字不算。"""
    noted("type: fix\nchange_log: |\n  ai_generated: 這是說明文字\n")
    assert run_hook(git_repo, notes_ref_sha(git_repo)).returncode == 0


def test_pushing_a_branch_is_none_of_the_hooks_business(git_repo, noted):
    noted("type: fix\nai_generated: {fields: [type]}")
    completed = run_hook(git_repo, notes_ref_sha(git_repo), remote_ref="refs/heads/master")
    assert completed.returncode == 0


def test_deleting_a_notes_ref_is_allowed(git_repo, noted):
    noted("type: fix\nai_generated: {fields: [type]}")
    assert run_hook(git_repo, EMPTY_SHA).returncode == 0
