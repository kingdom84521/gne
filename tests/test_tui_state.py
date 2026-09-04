"""狀態代數：純函式，不碰 git。"""

import pytest

from gne.core.git import CommitInfo
from gne.tui import state

FIRST = "a" * 40
SECOND = "b" * 40


def info(hash=FIRST, subject="feat: 東西", author_email="test@example.com"):
    return CommitInfo(
        hash=hash,
        branch_hash=hash,
        subject=subject,
        author="Test User",
        author_email=author_email,
        date="Fri Aug 28 19:00:00 2026 +0800",
    )


# --- 新備註的種子 ---


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("feat: 新功能", "feat"),
        ("fix: 修好了", "fix"),
        ("security: 補洞", "security"),
        ("skip: 明講", "skip"),
        ("fix(i18n): 帶 scope", "fix"),
        ("feat(client): 帶 scope", "feat"),
    ],
)
def test_a_prefix_that_matches_a_choice_becomes_the_seed(subject, expected):
    """哪個欄位跟著 convention 走由宣告檔說（x-follow-convention），scope 不影響對照。"""
    assert dict(state.seed_for(info(subject=subject))) == {"type": expected}


@pytest.mark.parametrize("subject", ["chore: 雜事", "refactor: 內部整理", "沒有冒號", ""])
def test_a_prefix_that_matches_nothing_is_left_to_the_default(subject):
    """對不上就不填——落到什麼值是 .gne/default-note 的事，不是這裡寫死 skip。"""
    assert dict(state.seed_for(info(subject=subject))) == {}
    assert dict(state.seed_for(info(subject=subject), {"type": "skip"})) == {"type": "skip"}


def test_seed_fills_nothing_but_what_it_can_derive():
    """欄位集合由 schema 決定，種子只填推得出來的那一個。"""
    assert list(state.seed_for(info())) == ["type"]


# --- 讀取目前內容 ---


def test_note_of_falls_back_to_the_seed_for_an_untouched_commit():
    editor = state.EditorState.of([info(subject="fix: x")])
    assert dict(editor.note_of(FIRST)) == {"type": "fix"}


def test_note_of_prefers_the_saved_note_over_the_seed():
    editor = state.EditorState.of([info(subject="fix: x")], saved={FIRST: {"type": "security"}})
    assert dict(editor.note_of(FIRST)) == {"type": "security"}


def test_note_of_prefers_pending_over_saved():
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}}).staged(
        FIRST, {"type": "fix"}
    )
    assert dict(editor.note_of(FIRST)) == {"type": "fix"}


def test_note_of_an_unknown_commit_is_empty():
    assert dict(state.EditorState.of([]).note_of(FIRST)) == {}


# --- 暫存 ---


def test_staging_returns_a_new_state_and_leaves_the_old_one_alone():
    before = state.EditorState.of([info()])
    after = before.staged(FIRST, {"type": "skip", "change_log": "改了"})
    assert before.pending_count == 0
    assert after.pending_count == 1


def test_staging_the_saved_value_again_clears_the_edited_mark():
    """存回原值還標成已編輯，已編輯標記就是騙人的。"""
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
    assert editor.staged(FIRST, {"type": "fix"}).is_edited(FIRST) is True
    assert editor.staged(FIRST, {"type": "fix"}).staged(FIRST, {"type": "feat"}).is_edited(
        FIRST
    ) is False


def test_staging_strips_empty_fields_before_comparing():
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
    staged = editor.staged(FIRST, {"type": "feat", "change_log": "", "redmine_ids": []})
    assert staged.is_edited(FIRST) is False


def test_staging_the_seed_on_an_unnoted_commit_is_an_edit():
    """用預設內容填就是寫入的意思：從「沒有備註」變成「有一筆」，那是異動。

    早先這裡釘的是相反的規則（只是開過表單就不算），但那條規則讓 skip 永遠寫不進去——
    skip 正好等於推測值，而九成的備註都是 skip。
    """
    editor = state.EditorState.of([info(subject="fix: x")])
    assert editor.staged(FIRST, {"type": "fix"}).is_edited(FIRST) is True


def test_pending_count_tracks_every_edited_commit():
    editor = (
        state.EditorState.of([info(FIRST), info(SECOND)])
        .staged(FIRST, {"type": "feat", "change_log": "一"})
        .staged(SECOND, {"type": "feat", "change_log": "二"})
    )
    assert editor.pending_count == 2


def test_discarding_restores_the_baseline():
    editor = (
        state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
        .staged(FIRST, {"type": "fix"})
        .discarded(FIRST)
    )
    assert editor.is_edited(FIRST) is False
    assert dict(editor.note_of(FIRST)) == {"type": "feat"}


def test_discarding_something_untouched_changes_nothing():
    editor = state.EditorState.of([info()])
    assert editor.discarded(FIRST) is editor


# --- 寫入之後 ---


def test_committed_moves_pending_into_saved():
    editor = state.EditorState.of([info()]).staged(FIRST, {"type": "fix", "change_log": "內容"})
    after = editor.committed([FIRST])
    assert after.pending_count == 0
    assert dict(after.saved[FIRST]) == {"type": "fix", "change_log": "內容"}


def test_committed_leaves_the_ones_that_were_not_written():
    editor = (
        state.EditorState.of([info(FIRST), info(SECOND)])
        .staged(FIRST, {"type": "fix"})
        .staged(SECOND, {"type": "security"})
    )
    after = editor.committed([FIRST])
    assert after.is_edited(FIRST) is False
    assert after.is_edited(SECOND) is True


# --- 不可變 ---


def test_the_state_cannot_be_mutated_in_place():
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
    with pytest.raises(TypeError):
        editor.saved[FIRST]["type"] = "fix"


# --- 預覽看到的與要編輯的不是同一件事 ---


def test_a_commit_with_no_note_previews_as_empty():
    """種子是編輯的起點，不是既有內容；預覽講成已經有備註會誤導。"""
    editor = state.EditorState.of([info(subject="fix: x")])
    assert dict(editor.written_note_of(FIRST)) == {}
    assert dict(editor.note_of(FIRST)) == {"type": "fix"}


def test_a_saved_note_previews_as_itself():
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
    assert dict(editor.written_note_of(FIRST)) == {"type": "feat"}


def test_a_staged_edit_previews_as_the_staged_content():
    editor = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}}).staged(
        FIRST, {"type": "fix", "change_log": "改了"}
    )
    assert dict(editor.written_note_of(FIRST))["change_log"] == "改了"


# --- AI 產生的備註 ---


AI_MARKER = True


def ai_state():
    return state.EditorState.of(
        [info()], saved={FIRST: {"type": "fix", "ai_generated": AI_MARKER}}
    )


def test_a_note_the_ai_wrote_is_flagged():
    assert ai_state().is_ai_generated(FIRST) is True


def test_a_note_a_human_wrote_is_not_flagged():
    written = state.EditorState.of([info()], saved={FIRST: {"type": "fix"}})
    assert written.is_ai_generated(FIRST) is False


def test_an_unwritten_commit_is_not_flagged():
    assert state.EditorState.of([info()]).is_ai_generated(FIRST) is False


def test_confirming_an_ai_note_untouched_still_counts_as_an_edit():
    """欄位一字未改，記號卻要消失——那是一次真的異動，不能被當成沒動過。"""
    staged = ai_state().staged(FIRST, {"type": "fix"})
    assert staged.is_edited(FIRST) is True
    assert dict(staged.pending[FIRST]) == {"type": "fix"}


# --- 用預設內容填算不算異動 ---


def test_accepting_the_seed_on_an_unnoted_commit_is_an_edit():
    """沒有備註 → 有一筆 skip。這是九成備註的寫入路徑，不能被當成沒動過。"""
    fresh = state.EditorState.of([info(subject="chore: 內部整理")])
    staged = fresh.staged(FIRST, {"type": "skip"})
    assert staged.is_edited(FIRST) is True
    assert dict(staged.pending[FIRST]) == {"type": "skip"}


def test_re_staging_the_stored_note_is_not_an_edit():
    written = state.EditorState.of([info()], saved={FIRST: {"type": "feat"}})
    assert written.staged(FIRST, {"type": "feat"}).is_edited(FIRST) is False


def test_staging_nothing_on_an_unnoted_commit_is_not_an_edit():
    """每個欄位都空的備註不該被寫進去。"""
    fresh = state.EditorState.of([info()])
    assert fresh.staged(FIRST, {"type": "", "change_log": ""}).is_edited(FIRST) is False


# --- 預設值：呼叫端讀好傳進來，這一層不碰檔案 ---


def test_a_subject_that_declares_its_type_beats_the_default():
    """`fix:` 開頭的 commit 比任何預設值都具體。"""
    seeded = state.seed_for(info(subject="fix: 修好了"), {"type": "skip"})
    assert dict(seeded) == {"type": "fix"}


def test_a_subject_that_declares_nothing_falls_back_to_the_default():
    seeded = state.seed_for(info(subject="refactor: 內部整理"), {"type": "feat"})
    assert dict(seeded) == {"type": "feat"}


def test_the_default_can_carry_more_than_the_type():
    seeded = state.seed_for(info(subject="chore: 雜事"), {"type": "skip", "change_log": "n/a"})
    assert dict(seeded) == {"type": "skip", "change_log": "n/a"}


def test_without_a_default_an_unrecognised_subject_seeds_nothing():
    assert dict(state.seed_for(info(subject="沒有冒號"))) == {}


def test_the_state_hands_the_default_to_every_unwritten_commit():
    editor = state.EditorState.of([info(subject="chore: 雜事")], default={"type": "feat"})
    assert dict(editor.baseline_of(FIRST)) == {"type": "feat"}
