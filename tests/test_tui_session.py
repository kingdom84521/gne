"""狀態與 repository 的接縫：載入與批次寫入。"""

import pytest

from gne.core import git, provenance
from gne.core.entity import NoteController
from gne.tui import session

LOCAL = {"schematic": "yaml", "fetch": False, "push": False}


@pytest.fixture
def controller():
    return NoteController(LOCAL)


# --- 載入 ---


def test_load_lists_only_unnoted_commits(controller, git_repo, commit):
    base = commit("feat: base")
    noted = commit("feat: 已經寫過了")
    plain = commit("feat: 還沒寫")
    controller.add({"type": "feat"}, noted)
    loaded = session.load(controller, f"{base}...master")
    assert [item.hash for item in loaded.commits] == [plain]


def test_load_can_keep_the_noted_ones(controller, git_repo, commit):
    base = commit("feat: base")
    noted = commit("feat: 已經寫過了")
    controller.add({"type": "feat"}, noted)
    loaded = session.load(controller, f"{base}...master", unnoted_only=False)
    assert noted in [item.hash for item in loaded.commits]
    assert dict(loaded.saved[noted]) == {"type": "feat"}


def test_load_filters_by_author_email(controller, git_repo, commit):
    base = commit("feat: base")
    commit("feat: 別人的", author="Other <other@example.com>")
    mine = commit("feat: 我的")
    loaded = session.load(controller, f"{base}...master", author_email="test@example.com")
    assert [item.hash for item in loaded.commits] == [mine]


def test_load_for_a_single_commit_keeps_it_even_when_noted(controller, git_repo, commit):
    commit("feat: base")
    head = commit("feat: 已經寫過了")
    controller.add({"type": "feat"}, head)
    loaded = session.load(controller, only=head)
    assert [item.hash for item in loaded.commits] == [head]
    assert dict(loaded.saved[head]) == {"type": "feat"}


def test_load_reads_the_note_listing_once(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    for index in range(10):
        commit(f"feat: {index}")
    calls: list[tuple[str, ...]] = []
    original_run = git._run

    def counting_run(*arguments: str, **keywords):
        calls.append(arguments)
        return original_run(*arguments, **keywords)

    monkeypatch.setattr(git, "_run", counting_run)
    session.load(controller, f"{base}...master")
    assert len([call for call in calls if call[:2] == ("notes", "list")]) == 1


# --- 批次寫入 ---


def test_save_writes_every_pending_note(controller, git_repo, commit):
    base = commit("feat: base")
    first = commit("feat: 一")
    second = commit("fix: 二")
    state = (
        session.load(controller, f"{base}...master")
        .staged(first, {"type": "feat", "change_log": "第一筆"})
        .staged(second, {"type": "fix", "change_log": "第二筆"})
    )
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.ok is True
    assert controller.show(first)["change_log"] == "第一筆"
    assert controller.show(second)["change_log"] == "第二筆"


def test_save_promotes_written_notes_into_the_returned_state(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("feat: 一")
    state = session.load(controller, f"{base}...master").staged(head, {"type": "feat", "change_log": "內容"})
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.state.pending_count == 0
    assert dict(outcome.state.saved[head]) == {"type": "feat", "change_log": "內容"}


def test_save_pushes_once_for_the_whole_batch(controller, git_repo, commit, origin, monkeypatch):
    base = commit("feat: base")
    first = commit("feat: 一")
    second = commit("fix: 二")
    state = (
        session.load(controller, f"{base}...master")
        .staged(first, {"type": "feat", "change_log": "一"})
        .staged(second, {"type": "fix", "change_log": "二"})
    )
    pushes: list[int] = []
    monkeypatch.setattr(git, "notes_push", lambda remote: pushes.append(remote))
    session.save_pending(state, controller, push=True)
    assert len(pushes) == 1


def test_save_does_not_push_when_asked_not_to(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    head = commit("feat: 一")
    state = session.load(controller, f"{base}...master").staged(
        head, {"type": "feat", "change_log": "內容"}
    )
    pushes: list[int] = []
    monkeypatch.setattr(git, "notes_push", lambda remote: pushes.append(remote))
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.written == (head,)
    assert pushes == []


def test_save_does_not_push_when_nothing_was_written(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    commit("feat: 一")
    state = session.load(controller, f"{base}...master")
    pushes: list[int] = []
    monkeypatch.setattr(git, "notes_push", lambda remote: pushes.append(remote))
    session.save_pending(state, controller, push=True)
    assert pushes == []


def test_a_note_the_schema_refuses_is_reported_not_raised(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("feat: 一")
    state = session.load(controller, f"{base}...master").staged(head, {"type": "不存在的種類"})
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.ok is False
    assert head in outcome.failures


def test_a_refused_note_stays_pending(controller, git_repo, commit):
    """寫不進去卻把暫存清掉，使用者的輸入就消失了。"""
    base = commit("feat: base")
    head = commit("feat: 一")
    state = session.load(controller, f"{base}...master").staged(head, {"type": "不存在的種類"})
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.state.is_edited(head) is True


def test_one_bad_note_does_not_stop_the_good_ones(controller, git_repo, commit):
    base = commit("feat: base")
    good = commit("feat: 好的")
    bad = commit("fix: 壞的")
    state = (
        session.load(controller, f"{base}...master")
        .staged(good, {"type": "feat", "change_log": "寫得進去"})
        .staged(bad, {"type": "不存在的種類"})
    )
    outcome = session.save_pending(state, controller, push=False)
    assert outcome.written == (good,)
    assert controller.show(good)["change_log"] == "寫得進去"


# --- 只看待人工確認的那些 ---


def test_load_can_list_only_the_ai_generated_ones(controller, git_repo, commit):
    base = commit("feat: base")
    ai_written = commit("fix: AI 填的")
    human_written = commit("fix: 人填的")
    unwritten = commit("fix: 還沒填")
    controller.add(provenance.stamped({"type": "fix"}, ["type"]), ai_written)
    controller.add({"type": "fix"}, human_written)
    loaded = session.load(controller, f"{base}...master", ai_only=True)
    assert [item.hash for item in loaded.commits] == [ai_written]
    assert unwritten


def test_the_ai_filter_overrides_the_unnoted_only_default(controller, git_repo, commit):
    """待確認的備註本來就寫進去了——沿用「只看沒填的」會一筆都列不出來。"""
    base = commit("feat: base")
    ai_written = commit("fix: AI 填的")
    controller.add(provenance.stamped({"type": "fix"}, ["type"]), ai_written)
    loaded = session.load(controller, f"{base}...master", ai_only=True, unnoted_only=True)
    assert [item.hash for item in loaded.commits] == [ai_written]


def test_a_failed_push_does_not_lose_track_of_what_was_written(controller, git_repo, commit):
    """推不出去不代表沒寫進去——審閱途中未確認的備註擋著推送，這是常態。"""
    base = commit("feat: base")
    head = commit("feat: 一")
    state = session.load(controller, f"{base}...master").staged(
        head, {"type": "feat", "change_log": "內容"}
    )
    outcome = session.save_pending(state, controller, push=True)
    assert outcome.written == (head,)
    assert outcome.ok is False
    assert outcome.sync_failure
    assert outcome.state.pending_count == 0
    assert controller.show(head) == {"type": "feat", "change_log": "內容"}
