import pytest

from conftest import run_git
from gne.core import git, provenance
from gne.core.entity import ERROR_ID, NoteController, NoteError, NoteSyncError

LOCAL = {"schematic": "yaml", "fetch": False, "push": False}


@pytest.fixture
def controller():
    return NoteController(LOCAL)


def test_round_trip(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "feat", "change_log": "做了東西"}, head)
    assert controller.show(head) == {"type": "feat", "change_log": "做了東西"}
    assert controller.is_exist(head) is True
    controller.remove(head)
    assert controller.is_exist(head) is False


def test_empty_values_are_stripped_before_storing(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "skip", "change_log": "", "redmine_ids": []}, head)
    assert git.notes_show(head) == "type: skip"


def test_unicode_is_stored_readably(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "fix", "change_log": "修好了中文"}, head)
    assert "修好了中文" in git.notes_show(head)


def test_adding_twice_without_force_is_refused(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "skip"}, head)
    with pytest.raises(NoteError) as caught:
        controller.add({"type": "feat"}, head)
    assert caught.value.id is ERROR_ID.NOTE_EXISTED


def test_force_overwrites(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "skip"}, head)
    controller.add({"type": "feat"}, head, isForce=True)
    assert controller.show(head)["type"] == "feat"


def test_unknown_commit_is_reported(controller, git_repo, commit):
    commit()
    with pytest.raises(NoteError) as caught:
        controller.add({"type": "skip"}, "definitely-not-a-ref")
    assert caught.value.id is ERROR_ID.COMMIT_NOT_FOUND


def test_removing_an_absent_note_is_reported(controller, git_repo, commit):
    head = commit()
    with pytest.raises(NoteError) as caught:
        controller.remove(head)
    assert caught.value.id is ERROR_ID.NOTE_NOT_FOUND


def test_showing_an_absent_note_is_reported(controller, git_repo, commit):
    head = commit()
    with pytest.raises(NoteError) as caught:
        controller.show(head)
    assert caught.value.id is ERROR_ID.NOTE_NOT_FOUND


def test_invalid_note_is_refused_with_a_readable_reason(controller, git_repo, commit):
    head = commit()
    with pytest.raises(NoteError) as caught:
        controller.add({"type": "not-a-real-type"}, head)
    assert caught.value.id is ERROR_ID.MODEL_NOT_MATCHED
    assert "not-a-real-type" in str(caught.value)


def test_error_messages_name_the_commit(controller, git_repo, commit):
    head = commit()
    with pytest.raises(NoteError) as caught:
        controller.show(head)
    assert head[:10] in str(caught.value)


def test_reading_a_note_that_violates_the_schema_still_works_raw(controller, git_repo, commit):
    """prune 與 backup 必須讀得到壞資料，否則會被自己要處理的東西擋下。"""
    head = commit()
    git.notes_add(head, "type: ''\nchange_log: ''", force=False)
    with pytest.raises(NoteError):
        controller.show(head)
    assert controller.read_raw(head) == {"type": "", "change_log": ""}


def test_all_notes_returns_every_note_raw(controller, git_repo, commit):
    first = commit()
    second = commit()
    git.notes_add(first, "type: ''", force=False)
    controller.add({"type": "feat", "change_log": "x"}, second)
    assert controller.all_notes() == {
        first: {"type": ""},
        second: {"type": "feat", "change_log": "x"},
    }


# --- 與 origin 的同步 ---


def test_push_disabled_means_no_remote_contact(controller, git_repo, commit):
    """關掉推送就真的不碰 remote。"""
    head = commit()
    controller.add({"type": "skip"}, head)
    assert controller.is_exist(head) is True


def test_push_failure_is_reported_but_the_note_is_already_local(
    git_repo, commit, unreachable_origin
):
    """推不出去就是推不出去，但備註已經寫進本機了，不會因為推送失敗就不見。"""
    pushing = NoteController({"schematic": "yaml", "fetch": False, "push": True})
    head = commit()
    with pytest.raises(NoteSyncError):
        pushing.add({"type": "skip"}, head)
    assert git.notes_show(head) == "type: skip"


def test_a_repo_without_a_remote_writes_notes_and_says_nothing(git_repo, commit):
    """一個人在自己機器上記備註是完整的用法，不是壞掉的設定。"""
    alone = NoteController({"schematic": "yaml", "fetch": True, "push": True})
    head = commit()
    alone.add({"type": "skip"}, head)
    assert git.notes_show(head) == "type: skip"
    assert alone.sync_notice is None


def test_an_explicit_push_without_a_remote_says_so(controller, git_repo, commit):
    """自動推送沒有對象是沒事；你明講要推的時候，得知道它推不出去。"""
    commit()
    with pytest.raises(NoteError) as caught:
        controller.push()
    assert caught.value.id is ERROR_ID.NO_REMOTE


def test_a_fetch_that_cannot_reach_the_remote_is_a_notice(git_repo, commit, unreachable_origin):
    """網路不通不該擋住你把手上這幾筆填完——取回失敗是說明，不是錯誤。"""
    fetching = NoteController({"schematic": "yaml", "fetch": True, "push": False})
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    assert fetching.all_notes() == {head: {"type": "skip"}}
    assert "取回" in (fetching.sync_notice or "")


def test_json_schematic_round_trips(git_repo, commit):
    controller = NoteController({"schematic": "json", "fetch": False, "push": False})
    head = commit()
    controller.add({"type": "fix", "change_log": "多行\n內容"}, head)
    assert controller.show(head) == {"type": "fix", "change_log": "多行\n內容"}


# --- 未經人工確認的備註不上 origin ---


def test_pushing_is_refused_while_a_note_waits_for_review(controller, git_repo, commit):
    """refs/notes 只有一個 ref，推一次就把所有備註送上去，所以整個推送都不能走。"""
    head = commit()
    controller.add(provenance.stamped({"type": "fix"}, ["type"]), head)
    with pytest.raises(NoteError) as caught:
        controller.push()
    assert caught.value.id is ERROR_ID.REVIEW_PENDING


def test_pushing_gets_through_once_the_marker_is_gone(
    controller, git_repo, commit, unreachable_origin
):
    """remote 連不上，所以「推送真的失敗」正是守門讓它過去的證據。"""
    head = commit()
    controller.add({"type": "fix"}, head)
    with pytest.raises(NoteSyncError):
        controller.push()


def test_unpushed_notes_do_not_stop_the_fetch(git_repo, commit, origin):
    """本機有還沒推的備註，仍然取得回 origin 的東西——取回不該被本機的進度擋住。"""
    fetching = NoteController({"schematic": "yaml", "fetch": True, "push": False})
    shared = commit()
    git.notes_add(shared, "type: skip", force=False)
    git.notes_push("origin")

    mine = commit()
    git.notes_add(mine, "type: fix", force=False)

    assert fetching.all_notes() == {shared: {"type": "skip"}, mine: {"type": "fix"}}
    assert fetching.sync_notice is None, "只是本機領先，沒什麼要說的"


def test_being_behind_brings_the_notes_back(git_repo, commit, origin):
    """origin 有、本機沒有的備註，取回之後就在了。"""
    fetching = NoteController({"schematic": "yaml", "fetch": True, "push": False})
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    run_git("update-ref", "-d", git.NOTES_REF, cwd=git_repo)

    assert fetching.all_notes() == {head: {"type": "skip"}}
    assert fetching.sync_notice is None


def test_divergence_is_reported_the_way_git_reports_it(git_repo, commit, origin):
    """兩邊各有各的：不動它，把兩個數字說出來並告訴你怎麼合併。"""
    fetching = NoteController({"schematic": "yaml", "fetch": True, "push": False})
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    shared = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)

    second = commit()
    git.notes_add(second, "type: fix", force=False)
    git.notes_push("origin")
    run_git("update-ref", git.NOTES_REF, shared, cwd=git_repo)
    git.notes_add(second, "type: feat", force=True)

    fetching.all_notes()
    assert "本機多 1 筆、origin 多 1 筆" in fetching.sync_notice
    assert "git notes merge origin/commits" in fetching.sync_notice
    assert fetching.show(second) == {"type": "feat"}, "分歧時不能動本機那一份"


def test_the_sync_notice_is_taken_once(git_repo, commit):
    """同一則訊息只該出現一次：畫面上說過，離開之後就不該再印一行在終端機上。"""
    fetching = NoteController({"schematic": "yaml", "fetch": False, "push": False})
    commit()
    fetching.sync_notice = "有話要說"
    assert fetching.take_sync_notice() == "有話要說"
    assert fetching.take_sync_notice() is None


# --- 欄位異動：宣告改了，既有備註要跟著改 ---


def test_renaming_a_field_rewrites_the_notes_that_carry_it(controller, git_repo, commit):
    """宣告的 additionalProperties 是 false，改名不同步就等於讓舊備註全部作廢。"""
    carrying = commit()
    controller.add({"type": "fix", "change_log": "修好了"}, carrying)
    untouched = commit()
    controller.add({"type": "skip"}, untouched)

    rewritten = controller.rename_field("change_log", "summary")

    assert rewritten == (carrying,)
    assert controller.all_notes()[carrying] == {"type": "fix", "summary": "修好了"}
    assert controller.all_notes()[untouched] == {"type": "skip"}


def test_dropping_a_field_takes_it_out_of_the_notes(controller, git_repo, commit):
    head = commit()
    controller.add({"type": "fix", "change_log": "修好了"}, head)

    assert controller.drop_field("change_log") == (head,)
    assert controller.all_notes()[head] == {"type": "fix"}


def test_the_affected_notes_can_be_counted_before_anything_changes(controller, git_repo, commit):
    """先講得出影響幾筆，才輪得到問要不要做。"""
    carrying = commit()
    controller.add({"type": "fix", "change_log": "修好了"}, carrying)
    commit()

    assert controller.notes_carrying("change_log") == (carrying,)
    assert controller.all_notes()[carrying]["change_log"] == "修好了"


def test_renaming_leaves_the_ai_marker_alone(controller, git_repo, commit):
    """ai_generated 不在宣告檔裡，欄位異動不該把它洗掉。"""
    head = commit()
    controller.add({"type": "fix", "change_log": "x", "ai_generated": True}, head)

    controller.rename_field("change_log", "summary")

    note = controller.all_notes()[head]
    assert note["ai_generated"] is True
    assert note["summary"] == "x"
