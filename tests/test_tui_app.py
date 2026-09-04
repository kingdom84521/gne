"""真的把 TUI 跑起來按鍵：run_test() 驅動，斷言看得到的東西。"""

import contextlib
import json
import threading

import pytest
from textual.widgets import Input, RadioButton, RadioSet

from gne.core import git, provenance
from gne.core.entity import NoteController
from gne.tui import app as tui_app
from gne.tui import keys, session
from gne.tui.app import GneApp
from gne.tui.screens.confirm import NO, YES
from gne.tui.screens import (
    CommitDetailScreen,
    CommitInfoScreen,
    ConfirmScreen,
    ShortcutsScreen,
    SuggestionScreen,
)
from gne.tui.widgets import CommitList, NotePreview, NotePrompt
from gne.tui.widgets import commit_list
from gne.tui.widgets.note_prompt import INPUT_ID, LOG_ID, QUESTION_ID

from gne.core import schema
from conftest import advisor_replying, fake_advisor, write_default_note
from tui_probe import colour_of, screen_text

LOCAL = {"schematic": "yaml", "fetch": False, "push": False}
SIZE = (110, 34)


@pytest.fixture
def controller():
    return NoteController(LOCAL)


def answer_box(app) -> Input:
    return app.query_one(f"#{INPUT_ID}", Input)


def choices(app) -> RadioSet:
    return app.query_one(RadioSet)


def question(app) -> str:
    return app.query_one(NotePrompt).question


async def answer(app, pilot, text=None):
    """回答目前那一題。text 為 None 就直接 Enter 保留原值。"""
    if text is not None:
        answer_box(app).value = text
    await pilot.press("enter")
    await pilot.pause()


async def settle(app, pilot):
    """等背景 worker 做完，並讓它回丟的訊息跑完一輪。"""
    for _ in range(3):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


def editor(controller, revision_range=None, **arguments):
    return GneApp(controller, revision_range=revision_range, push=False, **arguments)


# --- 啟動與瀏覽 ---


async def test_the_list_shows_the_unnoted_commits(controller, git_repo, commit):
    base = commit("feat: base")
    noted = commit("feat: 寫過了")
    plain = commit("fix: 還沒寫")
    controller.add({"type": "feat"}, noted)
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert [item.hash for item in app.state.commits] == [plain]


async def test_moving_down_updates_the_right_hand_preview(controller, git_repo, commit):
    base = commit("feat: base")
    first = commit("feat: 第一筆")
    second = commit("fix: 第二筆")
    controller.add({"type": "feat", "change_log": "第一筆的說明"}, first)
    controller.add({"type": "fix", "change_log": "第二筆的說明"}, second)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        starting = screen_text(app)
        await pilot.press("down")
        await pilot.pause()
        assert screen_text(app) != starting


async def test_the_preview_shows_the_field_titles_not_the_raw_keys(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix", "change_log": "看得懂的說明"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        shown = screen_text(app)
        assert "變更說明" in shown
        assert "change_log" not in shown


async def test_an_unfilled_commit_does_not_look_like_it_has_a_note(controller, git_repo, commit):
    base = commit("feat: base")
    commit("chore: 還沒填")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        shown = screen_text(app)
        assert "尚未填寫" in shown
        assert "變更種類" not in shown


async def test_the_prompt_opens_on_the_first_question_with_the_inferred_value(
    controller, git_repo, commit
):
    base = commit("feat: base")
    commit("fix: 還沒填")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert "變更種類" in question(app)
        assert "變更種類?" in screen_text(app), "問題要真的畫在畫面上"
        assert choices(app).pressed_index == 1, "預設要落在從標題推出來的 fix 上"
        assert "[feat / fix" not in question(app), "可選值是選得動的東西，不是印出來的文字"


async def test_the_list_carries_nothing_but_the_mark_and_the_hash(controller, git_repo, commit):
    """標題改由右側承擔，左側只留固定寬度的識別資訊。"""
    base = commit("feat: base")
    head = commit("fix: 一個很長很長長到會把列表撐開的標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        row = str(app.query_one(CommitList).get_option_at_index(0).prompt)
        assert row == f"[ ] {head[:10]}"


async def test_tab_no_longer_changes_the_list(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        before = str(app.query_one(CommitList).get_option_at_index(0).prompt)
        await pilot.press("tab")
        await pilot.pause()
        assert str(app.query_one(CommitList).get_option_at_index(0).prompt) == before


SLACK = 6  # 一列之外只容得下邊框、內距與捲軸


async def test_the_pane_is_barely_wider_than_one_row(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 一個很長很長長到會把列表撐開的標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.query_one(CommitList).content_region.width >= commit_list.ROW_WIDTH
        assert app.commit_pane.outer_size.width <= commit_list.ROW_WIDTH + SLACK


async def test_the_pane_width_ignores_how_long_the_subjects_are(controller, git_repo, commit):
    """標題已經不在左側，它再長也不該影響左側佔多寬。"""
    base = commit("feat: base")
    commit("fix: 短")
    narrow = editor(controller, f"{base}...master")
    async with narrow.run_test(size=SIZE) as pilot:
        await settle(narrow, pilot)
        with_short_subject = narrow.commit_pane.outer_size.width

    commit("fix: " + "很長的標題" * 20)
    wide = editor(controller, f"{base}...master")
    async with wide.run_test(size=SIZE) as pilot:
        await settle(wide, pilot)
        assert wide.commit_pane.outer_size.width == with_short_subject


async def test_a_scrolling_list_does_not_clip_the_hash(controller, git_repo, commit):
    """列表長到要捲動時，捲軸只能佔它自己那幾格，不能吃掉 hash。"""
    base = commit("feat: base")
    for index in range(30):
        commit(f"fix: 第 {index} 筆")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=(96, 16)) as pilot:
        await settle(app, pilot)
        listing = app.query_one(CommitList)
        assert listing.content_region.width >= commit_list.ROW_WIDTH
        assert app.state.commits[0].hash[:10] in screen_text(app)


async def test_the_subject_moves_to_the_right_hand_pane(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題要看得到")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert "fix: 標題要看得到" in screen_text(app)


async def test_the_subject_stands_out_from_the_note_body(controller, git_repo, commit):
    """左側不再顯示標題，右側就得撐起辨識——顏色與字重都要跟內文分得開。"""
    base = commit("feat: base")
    commit("fix: 標題要看得到")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        subject = app.query_one("#commit-subject")
        body = app.query_one(NotePreview)
        assert subject.styles.color != body.styles.color
        assert "bold" in str(subject.styles.text_style)




# --- 進入編輯 ---


async def test_enter_switches_the_right_pane_to_the_form(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is True
        assert app.query_one(NotePreview).display is False


async def test_the_commit_list_stays_put_while_editing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        before = app.query_one(CommitList).highlighted
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one(CommitList).highlighted == before


async def test_a_new_note_opens_with_the_type_inferred_from_the_subject(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 修好了")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert choices(app).pressed_index == 1


async def test_every_declared_field_gets_asked_in_declaration_order(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        for field in schema.note_fields():
            assert field.title in question(app), f"{field.key} 沒有被問到"
            await answer(app, pilot)
        assert app.query_one(NotePrompt).asking is False


# --- 編輯與暫存 ---


async def test_ctrl_s_stages_the_edit_and_returns_to_browsing(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "寫好的說明")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is False
        assert app.state.is_edited(head) is True
        assert dict(app.state.note_of(head))["change_log"] == "寫好的說明"


async def test_a_staged_commit_is_marked_in_the_list(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "[*]" in str(app.query_one(CommitList).get_option_at_index(0).prompt)


async def test_accepting_the_suggestion_without_typing_is_a_real_edit(controller, git_repo, commit):
    """從「沒有備註」變成「有一筆 skip」是一次異動。九成的備註都是這樣寫進去的。"""
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    head = commit("chore: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.state.pending_count == 1
        assert dict(app.state.pending[head]) == {"type": "skip"}


async def test_re_saving_a_note_that_is_already_stored_is_not_an_edit(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix", "change_log": "人寫的"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_cancelling_after_a_change_asks_before_dropping_it(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_cancelling_without_a_change_leaves_straight_away(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)
        assert app.query_one(NotePrompt).display is False


# --- 連按兩次 Esc 清空輸入 ---


async def test_one_escape_only_warns(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        await pilot.press("escape")
        await pilot.pause()
        assert "再按一次 Esc 清空輸入" in screen_text(app)
        assert answer_box(app).value == "打了字"


async def test_two_escapes_clear_what_was_typed(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert answer_box(app).value == ""
        assert app.query_one(NotePrompt).display is True, "清空是清內容，不是離開編輯"
        assert "再按一次" not in screen_text(app)


async def test_escape_on_a_choice_question_has_nothing_to_clear(controller, git_repo, commit):
    """選項題沒有輸入框，不掛一條「再按一次」然後什麼也不會發生。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert "再按一次" not in screen_text(app)


async def test_the_second_escape_has_to_come_within_the_window(
    controller, git_repo, commit, monkeypatch
):
    monkeypatch.setattr(tui_app, "DOUBLE_PRESS_SECONDS", 0.05)
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause(0.2)
        assert "再按一次" not in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        assert answer_box(app).value == "打了字"


async def test_a_different_two_step_key_starts_over(controller, git_repo, commit):
    """掛著的提示永遠只說一件事：按了 esc 又按 ctrl+c，不會變成「已經按過一次」。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running is True
        assert "再按一次 Ctrl+C 不儲存直接離開" in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        assert answer_box(app).value == "打了字"


async def test_ctrl_w_still_leaves_backspace_alone(controller, git_repo, commit):
    """取消綁在 ctrl+w 上，退格照樣刪字。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        answer_box(app).cursor_position = 3
        await pilot.press("backspace")
        await pilot.pause()
        assert answer_box(app).value == "打了"
        assert app.query_one(NotePrompt).display is True


# --- 回到問答就能直接打字 ---


async def test_clicking_the_question_puts_the_cursor_back(controller, git_repo, commit):
    """問題與可選值都在同一塊裡，點哪裡都是「我要回這一題」。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await pilot.click("#commits")
        await pilot.pause()
        await pilot.click(f"#{QUESTION_ID}")
        await pilot.pause()
        assert app.focused is answer_box(app)


async def test_clicking_the_answered_lines_does_not_take_the_cursor(controller, git_repo, commit):
    """答過的那幾行是給人看的，點它一下不該讓打字失去去處。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await pilot.click(f"#{LOG_ID}")
        await pilot.pause()
        assert app.focused is answer_box(app)


async def test_closing_a_dialog_leaves_the_cursor_in_the_question(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is answer_box(app)


async def test_the_cursor_goes_back_to_the_choices_of_a_choice_question(
    controller, git_repo, commit
):
    """選項題回來的是那一排可選值，不是藏起來的輸入框。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#commits")
        await pilot.pause()
        await pilot.click(f"#{QUESTION_ID}")
        await pilot.pause()
        assert app.focused is choices(app)


# --- 打字不能觸發指令 ---


async def test_typing_s_into_a_field_does_not_trigger_save(controller, git_repo, commit):
    """瀏覽模式的按鍵掛在列表上；焦點在表單時它們必須失效。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await pilot.press("s", "q", "r", "i")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is True
        assert answer_box(app).value == "sqri"


async def test_typing_q_into_a_single_line_field_does_not_quit(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot)
        await pilot.press("1", "2", "3")
        await pilot.pause()
        assert "識別碼" in question(app)
        assert answer_box(app).value == "123"


# --- 識別碼欄位 ---


async def test_a_non_numeric_identifier_is_reported_not_dropped(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot)
        await answer(app, pilot, "abc")
        assert app.query_one(NotePrompt).display is True
        assert "識別碼" in question(app), "答錯的那一題要留在原地再問一次"
        assert answer_box(app).value == "abc", "打進去的東西不能被丟掉"
        assert "只接受" in screen_text(app)
        assert app.state.pending_count == 0


async def test_identifiers_round_trip_through_the_prompt(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix", "redmine_ids": [12345, 67890]}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot)
        assert answer_box(app).value == "12345, 67890"


# --- 批次寫入 ---


async def test_s_writes_every_pending_note(controller, git_repo, commit):
    base = commit("feat: base")
    commit("feat: 一")
    commit("fix: 二")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        listed = [item.hash for item in app.state.commits]
        for position, _ in enumerate(listed):
            await pilot.press("enter")
            await pilot.pause()
            await answer(app, pilot)
            await answer(app, pilot, f"第 {position} 筆")
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
        assert app.state.pending_count == 2
        await pilot.press("s")
        await settle(app, pilot)
        assert app.state.pending_count == 0
    for position, revision in enumerate(listed):
        assert controller.show(revision)["change_log"] == f"第 {position} 筆"


async def test_saving_marks_the_rows_as_written(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "內容")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("s")
        await settle(app, pilot)
        assert "[✓]" in str(app.query_one(CommitList).get_option_at_index(0).prompt)


async def test_the_status_line_counts_what_is_waiting(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "內容")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "1 筆待寫入" in screen_text(app)


# --- 離開 ---


async def test_q_with_pending_edits_asks_first(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "還沒存")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_one_ctrl_c_warns_instead_of_leaving(controller, git_repo, commit):
    """離開會丟掉待寫入的東西，但為它開一個對話框太重——先掛一條提示，第二次才走。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running is True
        assert "再按一次 Ctrl+C 不儲存直接離開" in screen_text(app)


async def test_two_ctrl_c_leaves_without_writing_anything(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running is False
    assert git.notes_list() == {}, "待寫入的那一筆不該被寫進 refs/notes"


async def test_the_second_ctrl_c_has_to_come_within_the_window(
    controller, git_repo, commit, monkeypatch
):
    """隔了很久才按的那一次不是「再按一次」，它是新的第一次。"""
    monkeypatch.setattr(tui_app, "DOUBLE_PRESS_SECONDS", 0.05)
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+c")
        await pilot.pause()
        await pilot.pause(0.2)
        assert "再按一次" not in screen_text(app)
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running is True


async def test_the_warning_covers_the_shortcut_row_instead_of_pushing_it(
    controller, git_repo, commit
):
    """提示蓋在快捷鍵列上，不另外佔一行——版面不會因為按了一次 ctrl+c 而跳。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        before = app.query_one(CommitList).region.height
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert "ctrl+h" not in screen_text(app)
        assert app.query_one(CommitList).region.height == before


async def test_q_with_nothing_pending_just_leaves(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("q")
        await pilot.pause()
    assert app.is_running is False


# --- commit 詳情 ---


async def test_i_opens_the_detail_screen_with_both_tabs(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        await settle(app, pilot)
        assert isinstance(app.screen, CommitDetailScreen)
        assert "檔案列表" in screen_text(app)
        assert "file2.txt" in screen_text(app)


async def test_the_detail_screen_names_the_commit_it_is_showing(controller, git_repo, commit):
    """ModalScreen 預設垂直置中，標題很容易被推到畫面外。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        await settle(app, pilot)
        shown = screen_text(app)
        assert head[:10] in shown
        assert "fix: 東西" in shown


async def test_the_confirm_dialog_starts_on_the_affirmative_button(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "yes"


async def test_the_detail_screen_closes_on_escape(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        await settle(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CommitDetailScreen)


async def test_tab_switches_the_detail_tabs(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        await settle(app, pilot)
        from textual.widgets import TabbedContent

        assert app.screen.query_one(TabbedContent).active == "tab-files"
        await pilot.press("tab")
        await pilot.pause()
        assert app.screen.query_one(TabbedContent).active == "tab-diff"
        assert "diff --git" in screen_text(app)


# --- 單筆模式 ---


async def test_a_single_commit_opens_straight_into_the_form(controller, git_repo, commit):
    commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, only=head)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert [item.hash for item in app.state.commits] == [head]
        assert app.query_one(NotePrompt).display is True


async def test_a_single_commit_writes_on_ctrl_s(controller, git_repo, commit):
    commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, only=head)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await answer(app, pilot)
        await answer(app, pilot, "單筆寫入")
        await pilot.press("ctrl+s")
        await settle(app, pilot)
    assert controller.show(head)["change_log"] == "單筆寫入"


# --- 舊資料 ---


async def test_a_note_with_an_unknown_type_opens_without_crashing(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    git.notes_add(head, "type: ''\nchange_log: 有內容", force=False)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is True
        await answer(app, pilot)
        assert answer_box(app).value == "有內容"


# --- 讀取期間的畫面 ---


@contextlib.contextmanager
def held_load(monkeypatch):
    """把 session.load 擋在門口，好觀察 commit 還沒回來時的畫面。"""
    gate = threading.Event()
    original = session.load

    def blocking(*arguments, **keywords):
        gate.wait(10)
        return original(*arguments, **keywords)

    monkeypatch.setattr(session, "load", blocking)
    try:
        yield gate
    finally:
        gate.set()


async def test_the_screen_says_it_is_loading_before_the_commits_arrive(
    controller, git_repo, commit, monkeypatch
):
    """讀取中和「一筆都沒有」是兩件事，畫面不能長得一樣。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.loading_commits is True
            shown = screen_text(app)
            assert "讀取" in shown
            assert "沒有可編輯的 commit" not in shown
            gate.set()
            await settle(app, pilot)


async def test_the_commit_pane_shows_a_loading_indicator(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.commit_list.loading is True
            gate.set()
            await settle(app, pilot)
            assert app.commit_list.loading is False


async def test_the_loading_state_clears_once_the_commits_arrive(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.loading_commits is False
        assert "讀取" not in screen_text(app)


async def test_an_empty_result_is_not_reported_as_loading(controller, git_repo, commit):
    """區間內一筆都沒有時，要說沒有，不能一直卡在讀取中。"""
    base = commit("feat: base")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.loading_commits is False
        assert "沒有可編輯的 commit" in screen_text(app)


async def test_a_failed_load_does_not_leave_the_screen_loading(
    controller, git_repo, commit, monkeypatch
):
    """讀取失敗還讓轉圈圈轉下去，使用者只會一直等。"""
    base = commit("feat: base")
    commit("fix: 東西")

    def explode(*arguments, **keywords):
        raise git.GitError(("log",), 128, "fatal: bad revision")

    monkeypatch.setattr(session, "load", explode)
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.loading_commits is False
        assert app.commit_list.loading is False


async def test_reloading_shows_the_loading_state_again(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.loading_commits is False
        with held_load(monkeypatch) as gate:
            await pilot.press("r")
            await pilot.pause()
            assert app.loading_commits is True
            gate.set()
            await settle(app, pilot)
        assert app.loading_commits is False


async def test_the_list_keeps_its_width_while_loading(controller, git_repo, commit, monkeypatch):
    """寬度是 auto，讀取中一列都沒有時面板會塌掉，資料回來整個版面又跳一次。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            while_loading = app.commit_pane.outer_size.width
            assert while_loading >= commit_list.ROW_WIDTH
            gate.set()
            await settle(app, pilot)
            assert app.commit_pane.outer_size.width == while_loading


async def test_the_form_is_out_of_reach_while_loading(controller, git_repo, commit, monkeypatch):
    """表單一開始就得藏起來，否則初始焦點會落在看不見的欄位上。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.query_one(NotePrompt).display is False
            assert "儲存這筆" not in screen_text(app)
            gate.set()
            await settle(app, pilot)


async def test_there_is_always_a_visible_way_out(controller, git_repo, commit, monkeypatch):
    """讀取中列表沒有焦點，它那組按鍵不會生效——不能因此連怎麼離開都問不到。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert "ctrl+h" in screen_text(app)
            await pilot.press("ctrl+h")
            await pilot.pause()
            assert "離開" in screen_text(app)
            await pilot.press("escape")
            gate.set()
            await settle(app, pilot)


async def test_the_quit_key_leaves_even_while_loading(controller, git_repo, commit, monkeypatch):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    with held_load(monkeypatch) as gate:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+shift+q")
            await pilot.pause()
            assert app.is_running is False
            gate.set()


# --- 置頂只留 commit 標題，其餘資訊改成對話框 ---


def commit_date_year() -> str:
    return git.commit_date("HEAD").split()[-2]


async def test_the_heading_carries_nothing_but_the_subject(controller, git_repo, commit):
    """標題可能很長，置頂那條不該再被 hash 與日期分掉。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        shown = screen_text(app)
        assert "fix: 標題" in shown
        assert "test@example.com" not in shown
        assert "Test User" not in shown
        assert commit_date_year() not in shown


async def test_a_long_subject_gets_the_whole_strip(controller, git_repo, commit):
    base = commit("feat: base")
    tail = "結尾看得到"
    commit("fix: " + "很長的標題內容" * 8 + tail)
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert tail in screen_text(app)


async def test_ctrl_o_opens_the_commit_information(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 標題", author="Someone Else <else@example.com>")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, CommitInfoScreen)
        shown = screen_text(app)
        assert head[:10] in shown
        assert "Someone Else" in shown
        assert "else@example.com" in shown


async def test_the_information_dialog_reports_the_note_state(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert "尚未填寫" in screen_text(app)


async def test_the_information_dialog_names_the_cherry_pick_source(controller, git_repo, commit):
    base = commit("feat: base")
    original = commit("feat: 會被 cherry-pick 的")
    git.git_lines("checkout", "-q", "-b", "side", base)
    git.git_lines("cherry-pick", "-x", original)
    picked = git.git_line("rev-parse", "HEAD")
    app = editor(controller, f"{base}...side")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        shown = screen_text(app)
        assert original[:10] in shown
        assert picked[:10] in shown


async def test_ctrl_o_also_works_while_editing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, CommitInfoScreen)


async def test_escape_closes_the_information_dialog(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CommitInfoScreen)


async def test_the_information_dialog_appends_git_show(controller, git_repo, commit):
    """填備註要看的訊息內文與 diff 都在 git show 裡，不必為了看一眼再換一個畫面。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        shown = screen_text(app)
        assert "diff --git" in shown
        assert "+++ b/file2.txt" in shown


async def test_the_diff_keeps_the_colours_git_gave_it(controller, git_repo, commit):
    """顏色是 git 上的（--color=always），這裡只是別在路上把它弄丟。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        added = colour_of(app, "+")
        hunk = colour_of(app, "@@ -0,0 +1 @@")
        plain = colour_of(app, "diff --git a/file2.txt b/file2.txt")
        assert added is not None and hunk is not None
        assert len({added, hunk, plain}) == 3, "新增行、hunk 標頭與其餘文字要各是各的顏色"


async def test_a_long_git_show_scrolls_inside_the_dialog(controller, git_repo, commit):
    """diff 再長也不會把對話框撐破，也不會把關閉提示擠掉。"""
    base = commit("feat: base")
    (git_repo / "long.txt").write_text("\n".join(f"line {number}" for number in range(300)))
    commit("fix: 很長的一筆")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        scroll = app.screen.query_one("#commit-info-scroll")
        assert scroll.max_scroll_y > 0
        assert app.screen.query_one("#commit-info").region.height <= SIZE[1]
        assert "Esc 關閉" in screen_text(app)


async def test_the_information_dialog_is_wider_than_the_others(controller, git_repo, commit):
    """diff 讀得下去才有用：這一個對話框比只放幾行字的那些寬。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        assert app.screen.query_one("#commit-info").region.width > 76


async def test_the_information_dialog_says_so_when_git_show_fails(
    controller, git_repo, commit, monkeypatch
):
    """查不到就把原因說出來，不要留著「讀取中」讓人一直等。"""
    base = commit("feat: base")
    commit("fix: 標題")

    def refuse(_revision):
        raise git.GitError(("show",), 128, "壞掉了")

    monkeypatch.setattr(git, "commit_show", refuse)
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await settle(app, pilot)
        assert "壞掉了" in screen_text(app)


# --- 對話框的共通行為：壓暗背景、點外面關掉 ---


async def test_the_dialog_dims_what_is_behind_it(controller, git_repo, commit):
    """終端機沒有真正的半透明，但帶 alpha 的底色會把下層整片壓暗。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app.screen.styles.background.a < 1.0


async def test_clicking_outside_the_dialog_closes_it(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.click(offset=(0, 0))
        await pilot.pause()
        assert not isinstance(app.screen, CommitInfoScreen)


async def test_clicking_inside_the_dialog_keeps_it_open(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        box = app.screen.query_one(".dialog-box")
        await pilot.click(offset=box.region.center)
        await pilot.pause()
        assert isinstance(app.screen, CommitInfoScreen)


async def test_clicking_outside_the_confirmation_cancels_it(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.click(offset=(0, 0))
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)
        assert app.state.is_edited(head) is False


async def test_ctrl_i_opens_the_commit_information(controller, git_repo, commit):
    """終端機把 Tab 與 Ctrl+I 送成同一個位元組，但送得出真 ctrl+i 的終端機要能用。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert isinstance(app.screen, CommitInfoScreen)


async def test_ctrl_i_also_works_while_editing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert isinstance(app.screen, CommitInfoScreen)


async def test_tab_does_not_open_the_commit_information(controller, git_repo, commit):
    """ctrl+i 是 tab 的別名，綁在 BINDINGS 上會讓 Tab 也跳出對話框。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("tab")
        await pilot.pause()
        assert not isinstance(app.screen, CommitInfoScreen)


async def test_tab_still_moves_between_form_fields(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        first = app.focused
        await pilot.press("tab")
        await pilot.pause()
        assert not isinstance(app.screen, CommitInfoScreen)
        assert app.focused is not first


# --- 快捷鍵列只留 ctrl+h，完整清單在它叫出來的對話框裡 ---


async def test_the_footer_carries_only_the_shortcut_key(controller, git_repo, commit):
    """十幾顆鍵擠在同一列，那一列就從瞄一眼的提示變成要讀的東西。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=(140, 34)) as pilot:
        await settle(app, pilot)
        shown = screen_text(app)
        assert "ctrl+h" in shown
        for elsewhere in ("ctrl+shift+q", "commit 資訊", "全部寫入", "整批預設"):
            assert elsewhere not in shown, f"{elsewhere} 應該只在快捷鍵清單裡"


async def test_the_footer_stays_the_same_while_editing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=(140, 34)) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        shown = screen_text(app)
        assert "ctrl+h" in shown
        assert "ctrl+s" not in shown


async def test_ctrl_h_opens_the_shortcut_list(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert isinstance(app.screen, ShortcutsScreen)
        shown = screen_text(app)
        assert "全部寫入" in shown
        assert "整批預設" in shown


async def test_the_shortcut_list_scrolls_inside_a_short_terminal(controller, git_repo, commit):
    """終端機不夠高的時候捲的是清單本身，不是整個對話框——關閉提示要一直在最底下。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=(96, 22)) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert app.screen.query_one("#shortcuts").region.height <= 22
        assert app.screen.query_one("#shortcuts-scroll").max_scroll_y > 0
        assert "Esc 關閉" in screen_text(app)


async def test_the_shortcut_list_spells_out_the_modifiers(controller, git_repo, commit):
    """^q 是終端機老手的寫法，使用者不必知道脫字符號是什麼意思。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        shown = screen_text(app)
        assert "ctrl+shift+q" in shown
        assert "shift+a" in shown, "清單上要寫使用者真的要按的東西"
        assert "^" not in shown


async def test_backspace_opens_the_shortcut_list_too(controller, git_repo, commit):
    """多數終端機把 ctrl+h 送成 backspace 的那個位元組，那時也要叫得出來。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("backspace")
        await pilot.pause()
        assert isinstance(app.screen, ShortcutsScreen)


async def test_backspace_in_the_answer_box_still_deletes(controller, git_repo, commit):
    """輸入框自己吃掉 backspace，打字打到一半不會跳出清單。"""
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        answer_box(app).value = "打了字"
        answer_box(app).cursor_position = 3
        await pilot.press("backspace")
        await pilot.pause()
        assert not isinstance(app.screen, ShortcutsScreen)
        assert answer_box(app).value == "打了"


async def test_ctrl_h_closes_the_shortcut_list_again(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert not isinstance(app.screen, ShortcutsScreen)


async def test_escape_closes_the_shortcut_list(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ShortcutsScreen)


async def test_a_key_that_cannot_do_anything_says_so(controller, git_repo, commit, monkeypatch):
    """按下去才發現做不了，不如在清單上就看得出來——沒設 GNE_ADVISOR 就問不了顧問。"""
    monkeypatch.delenv("GNE_ADVISOR", raising=False)
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert "（未設定）" in screen_text(app)
        assert colour_of(app, "AI 建議") != colour_of(app, "全部寫入"), "做不了的那一行要暗一階"


async def test_a_key_that_works_says_nothing_extra(controller, git_repo, commit, monkeypatch):
    monkeypatch.setenv("GNE_ADVISOR", "cat")
    base = commit("feat: base")
    commit("fix: 標題")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert "未設定" not in screen_text(app)
        assert colour_of(app, "AI 建議") == colour_of(app, "全部寫入")


def test_the_shortcut_list_is_built_from_the_keys_that_are_bound():
    """清單不是另外抄的一份：綁在哪一個模式上、說明寫什麼，都是掛著的那條 Binding 說的。"""
    listed = keys.sections(
        browse=CommitList.BINDINGS,
        editing=NotePrompt.BINDINGS,
        anywhere=GneApp.BINDINGS,
        detail=CommitDetailScreen.BINDINGS,
    )
    for section, bound in zip(
        listed,
        (CommitList.BINDINGS, NotePrompt.BINDINGS, GneApp.BINDINGS, CommitDetailScreen.BINDINGS),
    ):
        for binding in bound:
            assert (
                keys.Shortcut(keys.spelled_out(binding), binding.description) in section.shortcuts
            ), f"{binding.key} 不在「{section.title}」裡"


def test_a_key_with_a_fallback_lists_both():
    """一條綁著好幾顆鍵就全部列出來，除非它自己指定了顯示方式。"""
    assert keys.spelled_out(keys.hidden("escape,i", "close", "返回")) == "esc / i"
    assert (
        keys.spelled_out(keys.hidden("ctrl+shift+q,ctrl+q", "leave", "離開", key_display="ctrl+shift+q"))
        == "ctrl+shift+q"
    )


# --- 審閱 AI 產生的備註 ---


def ai_noted(controller, revision):
    controller.add(provenance.stamped({"type": "fix", "change_log": "AI 寫的"}, ["type", "change_log"]), revision)


async def test_an_ai_generated_note_is_marked_apart_from_a_written_one(
    controller, git_repo, commit
):
    base = commit("feat: base")
    head = commit("fix: 東西")
    ai_noted(controller, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert "[?]" in str(app.query_one(CommitList).get_option_at_index(0).prompt)


async def test_the_preview_warns_that_a_human_has_not_seen_it(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    ai_noted(controller, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert "尚未人工確認" in screen_text(app)


async def test_cancelling_an_ai_note_without_typing_does_not_ask(controller, git_repo, commit):
    """記號不是使用者打的，不能拿它冒充「這一筆改過了」。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    ai_noted(controller, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)


async def test_confirming_an_ai_note_in_the_editor_clears_the_marker(
    controller, git_repo, commit
):
    """儲存這一筆就是確認：欄位照原樣寫回去，記號沒了。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    ai_noted(controller, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("s")
        await settle(app, pilot)
    assert controller.show(head) == {"type": "fix", "change_log": "AI 寫的"}


async def test_the_editor_can_walk_only_the_waiting_ones(controller, git_repo, commit):
    base = commit("feat: base")
    ai_written = commit("fix: AI 填的")
    human_written = commit("fix: 人填的")
    ai_noted(controller, ai_written)
    controller.add({"type": "fix"}, human_written)
    app = editor(controller, f"{base}...master", ai_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert [item.hash for item in app.state.commits] == [ai_written]


# --- 離開鍵：ctrl+q 會被 VS Code 吃掉，要按的是 ctrl+shift+q ---


async def test_the_legacy_quit_key_still_reaches_our_own_leave(controller, git_repo, commit):
    """Textual 自己把 ctrl+q 綁成硬離開。那條路必須繼續被我們蓋掉，否則有暫存也會直接關掉。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert app.is_running is True


async def test_the_displayed_quit_key_also_asks_before_dropping_work(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        await answer(app, pilot, "改了")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("ctrl+shift+q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_the_command_palette_is_off_so_nothing_bypasses_the_confirmation(
    controller, git_repo, commit
):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.ENABLE_COMMAND_PALETTE is False
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert app.is_running is True
        assert not isinstance(app.screen, ConfirmScreen)


# --- 用預設內容填：不進問答 ---


async def test_a_key_accepts_the_suggestion_without_opening_the_form(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    head = commit("chore: 內部整理")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is False
        assert dict(app.state.pending[head]) == {"type": "skip"}
        assert "[*]" in str(app.query_one(CommitList).get_option_at_index(0).prompt)


async def test_the_accepted_suggestion_is_what_gets_written(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    head = commit("chore: 內部整理")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("s")
        await settle(app, pilot)
    assert controller.show(head) == {"type": "skip"}


async def test_accepting_a_commit_that_already_has_a_note_changes_nothing(
    controller, git_repo, commit
):
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix", "change_log": "人寫的"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_accept_all_asks_first_and_then_stages_every_untouched_commit(
    controller, git_repo, commit
):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    first = commit("chore: 一")
    second = commit("refactor: 二")
    noted = commit("fix: 三")
    controller.add({"type": "fix"}, noted)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.pending_count == 2
        assert set(app.state.pending) == {first, second}


async def test_accept_all_declined_stages_nothing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("chore: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_the_confirmation_moves_between_its_buttons_with_the_arrows(
    controller, git_repo, commit
):
    """跟問答那一排可選值同一套：`←` `→` 選，`Enter` 確定。"""
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    commit("chore: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        assert app.focused.id == YES
        await pilot.press("right")
        await pilot.pause()
        assert app.focused.id == NO
        await pilot.press("left")
        await pilot.pause()
        assert app.focused.id == YES


async def test_enter_takes_the_button_the_arrows_landed_on(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    commit("chore: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)
        assert app.state.pending_count == 0


async def test_enter_on_the_default_button_confirms(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    commit("chore: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.pending_count == 1


async def test_accept_all_says_so_when_there_is_nothing_to_accept(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("A")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)
        assert app.state.pending_count == 0


async def test_the_accept_keys_are_on_the_shortcut_list(controller, git_repo, commit):
    base = commit("feat: base")
    commit("chore: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=(140, 34)) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+h")
        await pilot.pause()
        shown = screen_text(app)
        assert "用預設填" in shown
        assert "shift+a" in shown, "清單上要寫使用者真的要按的東西"
        assert "整批預設" in shown


# --- AI 建議：判斷仍然是人的，畫面只給依據 ---


ADVICE = {
    "suggestion": {"type": "feat", "change_log": "https://wiki.example.com/x/ABC123"},
    "reason": "這一筆新增了使用者看得到的搜尋範圍。",
    "evidence": [{"path": "src/client/a.ts", "lines": "10-20"}],
}


async def test_the_dialog_shows_the_suggestion_its_reason_and_where_to_look(
    controller, git_repo, commit, tmp_path, monkeypatch
):
    monkeypatch.setenv("GNE_ADVISOR", advisor_replying(tmp_path, ADVICE))
    base = commit("feat: base")
    commit("feat: 深色模式")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert isinstance(app.screen, SuggestionScreen)
        shown = screen_text(app)
        assert "功能" in shown
        assert "使用者看得到的搜尋範圍" in shown
        assert "src/client/a.ts:10-20" in shown


async def test_accepting_the_suggestion_stages_it_as_a_human_note(
    controller, git_repo, commit, tmp_path, monkeypatch
):
    monkeypatch.setenv("GNE_ADVISOR", advisor_replying(tmp_path, ADVICE))
    base = commit("feat: base")
    head = commit("feat: 深色模式")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        await pilot.press("y")
        await pilot.pause()
        assert dict(app.state.pending[head]) == ADVICE["suggestion"]
        await pilot.press("s")
        await settle(app, pilot)
    assert controller.show(head) == ADVICE["suggestion"]
    assert "ai_generated" not in controller.read_raw(head)


async def test_closing_the_dialog_stages_nothing(
    controller, git_repo, commit, tmp_path, monkeypatch
):
    monkeypatch.setenv("GNE_ADVISOR", advisor_replying(tmp_path, ADVICE))
    base = commit("feat: base")
    commit("feat: 深色模式")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_closing_before_the_answer_arrives_does_not_crash(
    controller, git_repo, commit, tmp_path, monkeypatch
):
    """問一次要幾十秒，中途關掉是必然會發生的事。顧問故意慢半秒，好讓關閉確實先發生。"""
    slow = fake_advisor(
        tmp_path,
        "import time\nsys.stdin.read()\ntime.sleep(0.5)\n"
        + f"print({json.dumps(json.dumps(ADVICE))})\n",
    )
    monkeypatch.setenv("GNE_ADVISOR", slow)
    base = commit("feat: base")
    commit("feat: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.is_running is True
        assert app.state.pending_count == 0


async def test_an_unconfigured_advisor_says_how_to_set_it_up(
    controller, git_repo, commit, monkeypatch
):
    monkeypatch.delenv("GNE_ADVISOR", raising=False)
    base = commit("feat: base")
    commit("feat: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert "GNE_ADVISOR" in screen_text(app)
        await pilot.press("y")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_an_advisor_that_fails_shows_its_own_words(
    controller, git_repo, commit, tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "GNE_ADVISOR",
        fake_advisor(tmp_path, "sys.stderr.write('主機上找不到 claude')\nsys.exit(3)\n"),
    )
    base = commit("feat: base")
    commit("feat: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert "找不到 claude" in screen_text(app)


# --- 可選值：一排四個，左右鍵選 ---


async def test_the_choices_are_a_row_you_can_move_through(controller, git_repo, commit):
    """v1 的 questionary.select 就是這種控制項。印成文字等於把它降級成說明。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        labels = [str(button.label) for button in choices(app).query(RadioButton)]
        assert labels == ["feat 功能", "fix 錯誤", "security 安全性", "skip 略過"]


async def test_at_most_four_choices_share_a_row(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert choices(app).styles.grid_size_columns == 4


async def test_the_arrow_keys_move_and_enter_picks(controller, git_repo, commit):
    """游標從預設值出發（fix），往右一格就是 security。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "變更說明" in question(app), "選定就是答完這一題，直接問下一題"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert dict(app.state.note_of(head))["type"] == "security"


async def test_the_cursor_starts_on_the_default_not_the_first_option(controller, git_repo, commit):
    """游標與顯示為已選的那一個必須是同一個，否則直接按 Enter 會選到別的東西。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert dict(app.state.note_of(head))["type"] == "fix"


async def test_moving_back_lands_on_the_earlier_choice(controller, git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert dict(app.state.note_of(head))["type"] == "feat"


async def test_the_chosen_value_and_its_label_both_land_in_the_transcript(
    controller, git_repo, commit
):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "變更種類: fix（錯誤）" in screen_text(app)


async def test_a_legacy_value_outside_the_choices_offers_no_default(
    controller, git_repo, commit
):
    """舊資料真的有 type: ''。那時候不預選任何一個，問題也說沒有預設值。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    git.notes_add(head, "type: ''\nchange_log: 舊資料", force=False)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert choices(app).pressed_index == -1
        assert "沒有預設值" in question(app)


# --- 預設值：新備註從 .gne/default-note 開始 ---


async def test_a_new_note_starts_from_the_default_file(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\nchange_log: n/a\n")
    base = commit("feat: base")
    head = commit("refactor: 內部整理")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert "用預設 skip" in question(app), "直接 Enter 會寫進去什麼，要看得見"
        await answer(app, pilot)
        assert app.query_one(NotePrompt).asking is False, "選了 skip 就不再問"
        # 沒問到的欄位仍然帶著預設值：不問不等於清掉。
        assert dict(app.state.note_of(head)) == {"type": "skip", "change_log": "n/a"}


async def test_the_commit_subject_still_beats_the_default(controller, git_repo, commit):
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    commit("fix: 修好了")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert "用預設 fix" in question(app)
        assert choices(app).pressed_index == 1


async def test_an_existing_note_says_keep_not_default(controller, git_repo, commit):
    """「保留原值」與「用預設值」是兩件事，問句要分得開。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "security", "change_log": "人寫的"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert "保留 security" in question(app)
        await answer(app, pilot)
        assert "保留：人寫的" in question(app)


async def test_the_question_and_its_answer_sit_in_one_filled_block(controller, git_repo, commit):
    """問句與回答是同一塊淡色長方形，填滿寬度。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        pane = app.query_one("#pane")
        asked = app.query_one("#prompt-question")
        box = answer_box(app)
        assert asked.background_colors[1] != pane.background_colors[1]
        assert box.background_colors[1] == asked.background_colors[1]
        assert asked.size.width == box.size.width == pane.size.width - 2


async def test_the_transcript_the_question_and_the_answer_share_a_left_edge(
    controller, git_repo, commit
):
    """答過的、正在問的、要打字的：左邊界是同一條，中間不能差一格。"""
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await answer(app, pilot)
        left = app.query_one(f"#{QUESTION_ID}").content_region.x
        assert app.query_one(f"#{LOG_ID}").content_region.x == left
        assert answer_box(app).content_region.x == left


async def test_the_choice_row_starts_where_the_question_starts(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 東西")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        drawn = screen_text(app).splitlines()
        asked = next(line for line in drawn if "變更種類?" in line)
        row = next(line for line in drawn if "feat 功能" in line)
        assert asked.index("變") == row.index("▐")


# --- 選了 skip 就不必再問 ---


async def test_choosing_skip_ends_the_questions_there(controller, git_repo, commit):
    """這一筆不進 release note，後面幾欄問了也沒有意義。"""
    write_default_note(git_repo, "type: skip\n")
    base = commit("feat: base")
    head = commit("refactor: 內部整理")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one(NotePrompt).display is False, "問完了就回到瀏覽"
        assert dict(app.state.note_of(head)) == {"type": "skip"}


async def test_choosing_a_real_type_keeps_asking(controller, git_repo, commit):
    base = commit("feat: base")
    commit("fix: 修好了")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "變更說明" in question(app)


async def test_switching_to_skip_does_not_throw_away_what_was_already_there(
    controller, git_repo, commit
):
    """不問不等於清掉：原本填過的內容留著。"""
    base = commit("feat: base")
    head = commit("fix: 東西")
    controller.add({"type": "fix", "change_log": "本來就寫過的說明"}, head)
    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("right", "right")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert dict(app.state.note_of(head)) == {
            "type": "skip",
            "change_log": "本來就寫過的說明",
        }
