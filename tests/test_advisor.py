"""顧問的契約：JSON 進、JSON 出，回來的東西一律不被信任。"""

import json
from pathlib import Path

import pytest

from conftest import advisor_replying, fake_advisor, run_git
from gne import advisor
from gne.core import git

REPLY = {
    "suggestion": {"type": "fix", "change_log": "修正了東西"},
    "reason": "因為 diff 裡把條件寫反了。",
    "evidence": [{"path": "src/client/a.ts", "lines": "10-20"}],
}


replying = advisor_replying


@pytest.fixture
def commit_info(git_repo, commit):
    revision = commit("fix: 東西")
    return git.commit_info(revision)


# --- 設定 ---


def test_without_the_env_var_there_is_nobody_to_ask(monkeypatch):
    monkeypatch.delenv(advisor.ADVISOR_ENV, raising=False)
    assert advisor.configured() is False
    with pytest.raises(advisor.AdvisorNotConfigured):
        advisor.command()


def test_the_command_is_split_like_a_shell_would(monkeypatch):
    monkeypatch.setenv(advisor.ADVISOR_ENV, "ssh advisor-host /path/to/advise.sh")
    assert advisor.command() == ("ssh", "advisor-host", "/path/to/advise.sh")


# --- 交出去的東西 ---


def test_the_request_carries_the_field_declarations_so_the_rules_stay_in_one_place(commit_info):
    """填寫規則是宣告檔的 x-prompt。顧問讀那一份，gne 不在這裡再抄一遍。"""
    payload = json.loads(advisor.request_payload(commit_info, {}))
    assert set(payload["fields"]) == {
        "type",
        "change_log",
        "redmine_ids",
        "spec_change",
        "data_migration",
    }
    assert payload["fields"]["type"]["x-prompt"]
    assert payload["fields"]["spec_change"]["x-human-only"] is True


def test_the_request_carries_the_commit_and_its_diff(commit_info):
    payload = json.loads(advisor.request_payload(commit_info, {}))
    assert payload["commit"]["subject"] == "fix: 東西"
    assert payload["commit"]["files"]
    assert payload["commit"]["diff_truncated"] is False


def test_the_request_hands_over_the_note_without_the_marker(commit_info):
    payload = json.loads(advisor.request_payload(commit_info, {"type": "fix", "ai_generated": True}))
    assert payload["note"] == {"type": "fix"}


def test_a_huge_diff_is_truncated_and_says_so(commit_info, monkeypatch):
    monkeypatch.setattr(git, "commit_diff", lambda _: "x" * (advisor.DIFF_LIMIT + 10))
    payload = json.loads(advisor.request_payload(commit_info, {}))
    assert len(payload["commit"]["diff"]) == advisor.DIFF_LIMIT
    assert payload["commit"]["diff_truncated"] is True


# --- 讀回來的東西 ---


def test_a_well_formed_reply_becomes_a_suggestion(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(advisor.ADVISOR_ENV, replying(tmp_path, REPLY))
    suggestion = advisor.ask(commit_info, {})
    assert suggestion.note == {"type": "fix", "change_log": "修正了東西"}
    assert suggestion.reason.startswith("因為")
    assert suggestion.evidence[0].path == "src/client/a.ts"
    assert suggestion.evidence[0].lines == "10-20"


def test_a_field_the_schema_never_declared_is_dropped(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(
        advisor.ADVISOR_ENV, replying(tmp_path, {"suggestion": {"type": "fix", "invented": "x"}})
    )
    suggestion = advisor.ask(commit_info, {})
    assert suggestion.note == {"type": "fix"}
    assert suggestion.ignored == ("invented",)


@pytest.mark.parametrize("key", ["spec_change", "data_migration"])
def test_a_human_only_field_is_dropped_even_when_suggested(tmp_path, commit_info, monkeypatch, key):
    """顧問也不能填人工欄位——那不是「別填」的請求，是填不進來。"""
    monkeypatch.setenv(
        advisor.ADVISOR_ENV, replying(tmp_path, {"suggestion": {"type": "fix", key: "規格動了"}})
    )
    suggestion = advisor.ask(commit_info, {})
    assert suggestion.note == {"type": "fix"}
    assert key in suggestion.ignored


def test_a_value_the_schema_refuses_is_reported_not_shown(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(advisor.ADVISOR_ENV, replying(tmp_path, {"suggestion": {"type": "bogus"}}))
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.ask(commit_info, {})
    assert "bogus" in str(caught.value)


def test_a_reply_without_a_suggestion_object_is_refused(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(advisor.ADVISOR_ENV, replying(tmp_path, {"reason": "只有理由"}))
    with pytest.raises(advisor.AdvisorError):
        advisor.ask(commit_info, {})


def test_output_that_is_not_json_is_refused(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(
        advisor.ADVISOR_ENV,
        fake_advisor(tmp_path, "sys.stdin.read()\nprint('我覺得應該填 skip')\n"),
    )
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.ask(commit_info, {})
    assert "JSON" in str(caught.value)


def test_a_failing_advisor_reports_its_own_words(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(
        advisor.ADVISOR_ENV,
        fake_advisor(tmp_path, "sys.stderr.write('找不到 claude')\nsys.exit(3)\n"),
    )
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.ask(commit_info, {})
    assert "找不到 claude" in str(caught.value)


def test_a_command_that_does_not_exist_is_reported(commit_info, monkeypatch):
    monkeypatch.setenv(advisor.ADVISOR_ENV, "/definitely/not/here")
    with pytest.raises(advisor.AdvisorError):
        advisor.ask(commit_info, {})


# --- 依據要點得進去 ---


def test_evidence_becomes_a_gitlab_blob_link(git_repo, commit, tmp_path, monkeypatch):
    run_git("remote", "add", "origin", "https://gitlab.example.com/acme/app.git", cwd=git_repo)
    revision = commit("fix: 東西")
    monkeypatch.setenv(advisor.ADVISOR_ENV, replying(tmp_path, REPLY))
    suggestion = advisor.ask(git.commit_info(revision), {})
    assert suggestion.evidence[0].url == (
        f"https://gitlab.example.com/acme/app/-/blob/{revision}/src/client/a.ts#L10-20"
    )


def test_an_ssh_remote_still_yields_a_web_link(git_repo, commit):
    run_git("remote", "add", "origin", "git@gitlab.example.com:acme/app.git", cwd=git_repo)
    revision = commit()
    assert advisor.blob_url(revision, "a.ts", "3") == (
        f"https://gitlab.example.com/acme/app/-/blob/{revision}/a.ts#L3"
    )


def test_without_a_remote_there_is_no_link_to_give(git_repo, commit):
    assert advisor.blob_url(commit(), "a.ts", "3") is None


def test_a_line_range_that_is_not_a_range_gets_no_anchor(git_repo, commit):
    run_git("remote", "add", "origin", "https://gitlab.example.com/acme/app.git", cwd=git_repo)
    revision = commit()
    assert advisor.blob_url(revision, "a.ts", "整個檔案").endswith("/a.ts")


def test_evidence_without_a_path_is_skipped(tmp_path, commit_info, monkeypatch):
    monkeypatch.setenv(
        advisor.ADVISOR_ENV,
        replying(tmp_path, {"suggestion": {"type": "skip"}, "evidence": [{"lines": "1-2"}, "垃圾"]}),
    )
    assert advisor.ask(commit_info, {}).evidence == ()


def test_credentials_in_the_remote_never_reach_the_link(git_repo, commit):
    """這個 repo 的 origin 把 access token 嵌在 URL 裡，而連結是要給人貼的。"""
    run_git(
        "remote",
        "add",
        "origin",
        "https://oauth2:glpat-notarealtoken@gitlab.example.com/acme/app.git",
        cwd=git_repo,
    )
    revision = commit()
    url = advisor.blob_url(revision, "a.ts", "3")
    assert url.startswith("https://gitlab.example.com/acme/app/-/blob/")
    assert "glpat" not in url
    assert "@" not in url


def test_a_remote_without_credentials_is_left_alone(git_repo, commit):
    run_git("remote", "add", "origin", "https://gitlab.example.com/acme/app.git", cwd=git_repo)
    revision = commit()
    assert advisor.blob_url(revision, "a.ts") == (
        f"https://gitlab.example.com/acme/app/-/blob/{revision}/a.ts"
    )


def test_a_suggestion_that_only_fills_one_field_is_fine(tmp_path, commit_info, monkeypatch):
    """建議是起點不是終點：只建議變更說明、不碰種類，是完全合理的一份建議。"""
    monkeypatch.setenv(advisor.ADVISOR_ENV, replying(tmp_path, {"suggestion": {"change_log": "說明"}}))
    assert advisor.ask(commit_info, {}).note == {"change_log": "說明"}
