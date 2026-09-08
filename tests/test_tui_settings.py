"""專案自己的設定改在畫面上：區間、新備註的起點、欄位宣告。

這三樣以前只能改檔案。fx 一個專案設一次就不再動，別人的用法不是這樣，所以每一樣
都要能在工具裡改完——而且改欄位不只是改宣告，既有的備註要跟著改。
"""

import json

import pytest
from textual.widgets import Input, Switch

from gne.core import defaults, git, schema
from gne.core.entity import NoteController
from gne.tui.app import GneApp
from gne.tui.screens import DefaultNoteScreen, FieldsScreen, RangeScreen
from gne.tui.screens.confirm import ConfirmScreen
from gne.core.fields import draft_of
from gne.tui.screens.fields import FieldFormScreen
from gne.tui.setup import FieldSetupApp

from conftest import run_git

LOCAL = {"schematic": "yaml", "fetch": False, "push": False}
SIZE = (110, 34)


@pytest.fixture
def controller():
    return NoteController(LOCAL)


@pytest.fixture
def declared_in_repo(git_repo, monkeypatch):
    """宣告檔放進這個 repo，讓畫面改的是真的檔案。"""
    monkeypatch.delenv(schema.SCHEMA_ENV, raising=False)
    target = git_repo / ".gne" / "note-schema.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(schema.EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    schema.forget_schema()
    yield target
    schema.forget_schema()


async def settle(app, pilot):
    for _ in range(3):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


def editor(controller, revision_range=None, **arguments):
    return GneApp(controller, revision_range=revision_range, push=False, **arguments)


# --- 區間 ---


async def test_the_range_can_be_changed_without_leaving(controller, git_repo, commit):
    base = commit("feat: base")
    later = commit("feat: 後來這一筆")
    app = editor(controller, f"{later}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert [item.hash for item in app.state.commits] == []

        await pilot.press("ctrl+r")
        await pilot.pause()
        assert isinstance(app.screen, RangeScreen)

        app.screen.query_one("#range-input", Input).value = f"{base}...master"
        await pilot.press("enter")
        await settle(app, pilot)

        assert [item.hash for item in app.state.commits] == [later]


async def test_a_range_git_cannot_resolve_is_refused_on_the_spot(controller, git_repo, commit):
    """打錯不該把人趕出去重來，也不該等掃描到一半才炸。"""
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()

        app.screen.query_one("#range-input", Input).value = "沒有這個東西...master"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, RangeScreen), "留在原地改"


async def test_the_first_run_is_asked_instead_of_being_thrown_out(controller, git_repo, commit):
    """沒有可以沿用的區間時，畫面自己問——不是報錯結束。"""
    commit()
    app = editor(controller, None)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert isinstance(app.screen, RangeScreen)


# --- 新備註的起點 ---


async def test_the_default_note_is_written_from_the_screen(
    controller, git_repo, commit, declared_in_repo
):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert isinstance(app.screen, DefaultNoteScreen)

        app.screen.query_one("#default-field-type", Input).value = "skip"
        await pilot.press("ctrl+s")
        await settle(app, pilot)

    assert defaults.default_note_path().is_file()
    assert defaults.default_note() == {"type": "skip"}


async def test_a_default_that_the_declaration_refuses_stays_on_screen(
    controller, git_repo, commit, declared_in_repo
):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+d")
        await pilot.pause()

        app.screen.query_one("#default-field-type", Input).value = "不是可選值"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, DefaultNoteScreen)
    assert not defaults.default_note_path().exists()


# --- 欄位宣告 ---


async def test_a_new_field_reaches_the_declaration_file(
    controller, git_repo, commit, declared_in_repo
):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert isinstance(app.screen, FieldsScreen)

        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, FieldFormScreen)

        app.screen.query_one("#field-form-key", Input).value = "reviewer"
        app.screen.query_one("#field-form-title", Input).value = "審閱者"
        app.screen.query_one("#field-form-prompt", Input).value = "誰看過這一筆。"
        app.screen.query_one("#field-form-input", Input).value = "text"
        await pilot.press("ctrl+s")
        await pilot.pause()

        await pilot.press("ctrl+s")
        await settle(app, pilot)

    written = json.loads(declared_in_repo.read_text(encoding="utf-8"))
    assert "reviewer" in written["properties"]
    assert written["properties"]["reviewer"]["x-prompt"] == "誰看過這一筆。"


async def test_a_field_without_a_prompt_is_refused(controller, git_repo, commit, declared_in_repo):
    """沒有填寫指示的欄位沒人填得出來——宣告檔本來就擋，表單先擋一次。"""
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        app.screen.query_one("#field-form-key", Input).value = "reviewer"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, FieldFormScreen), "留在表單上"


async def test_dropping_a_field_rewrites_the_notes_that_carry_it(
    controller, git_repo, commit, declared_in_repo
):
    """這是 UI 解不掉的那一半：宣告改了，備註不跟著改就整批作廢。"""
    base = commit("feat: base")
    head = commit("fix: 一")
    controller.add({"type": "fix", "change_log": "說明"}, head)

    app = editor(controller, f"{base}...master", unnoted_only=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()

        listing = app.screen.query_one("#fields-list")
        listing.highlighted = 1  # change_log
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        await pilot.press("y")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen), "會改到既有備註，要先問"

        await pilot.press("y")
        await settle(app, pilot)

    assert "change_log" not in json.loads(declared_in_repo.read_text(encoding="utf-8"))["properties"]
    assert controller.all_notes()[head] == {"type": "fix"}


# --- 表單能表達的東西，不能少於宣告檔 ---


@pytest.mark.parametrize("key", list(json.loads(schema.EXAMPLE_PATH.read_text("utf-8"))["properties"]))
def test_every_field_in_the_template_round_trips_through_the_form(key):
    """範本裡的每一欄都要能被表單讀進來、再原樣寫回去。

    這一條就是「UI 能做到宣告檔能做的全部」的機械式說法：表單少收一個關鍵字，
    帶著那個關鍵字的欄位就對不回去，這裡會紅。
    """
    document = json.loads(schema.EXAMPLE_PATH.read_text(encoding="utf-8"))
    declaration = document["properties"][key]

    draft = draft_of(key, declaration, key in document.get("required", []))

    assert draft.as_declaration() == declaration


async def test_choice_labels_and_conditions_are_written_from_the_form(
    controller, git_repo, commit, declared_in_repo
):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        app.screen.query_one("#field-form-key", Input).value = "impact"
        app.screen.query_one("#field-form-title", Input).value = "影響"
        app.screen.query_one("#field-form-prompt", Input).value = "影響有多大。"
        app.screen.query_one("#field-form-input", Input).value = "choice"
        app.screen.query_one("#field-form-choices", Input).value = "big=很大, small=不大"
        app.screen.query_one("#field-form-ignore_when", Input).value = "type=skip"
        await pilot.press("ctrl+s")
        await pilot.pause()

        await pilot.press("ctrl+s")
        await settle(app, pilot)

    written = json.loads(declared_in_repo.read_text(encoding="utf-8"))["properties"]["impact"]
    assert written["enum"] == ["big", "small"]
    assert written["x-choice-labels"] == {"big": "很大", "small": "不大"}
    assert written["x-ignore-when"] == {"type": "skip"}


async def test_a_condition_written_without_a_value_is_refused(
    controller, git_repo, commit, declared_in_repo
):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        app.screen.query_one("#field-form-key", Input).value = "impact"
        app.screen.query_one("#field-form-prompt", Input).value = "影響有多大。"
        app.screen.query_one("#field-form-ignore_when", Input).value = "type"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, FieldFormScreen), "留在表單上"


async def test_a_condition_naming_a_field_that_does_not_exist_is_refused(
    controller, git_repo, commit, declared_in_repo
):
    """宣告檔本來就擋這件事，所以畫面上按儲存時擋得住，不會寫出壞掉的宣告。"""
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        app.screen.query_one("#field-form-key", Input).value = "impact"
        app.screen.query_one("#field-form-prompt", Input).value = "影響有多大。"
        app.screen.query_one("#field-form-ignore_when", Input).value = "沒有這一欄=x"
        await pilot.press("ctrl+s")
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, FieldsScreen), "留在欄位一覽上"


# --- gne init 問出來的欄位 ---


async def test_init_asks_and_produces_only_what_was_answered(git_repo, monkeypatch):
    """init 不塞一份現成的欄位進來：畫面一開始是空的，有幾欄是問出來的。"""
    monkeypatch.delenv(schema.SCHEMA_ENV, raising=False)
    setup = FieldSetupApp()
    async with setup.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(setup.screen, FieldsScreen)

        await pilot.press("a")
        await pilot.pause()
        setup.screen.query_one("#field-form-key", Input).value = "impact"
        setup.screen.query_one("#field-form-title", Input).value = "影響"
        setup.screen.query_one("#field-form-prompt", Input).value = "影響有多大。"
        await pilot.press("ctrl+s")
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

    assert setup.return_value is not None
    assert list(setup.return_value.document["properties"]) == ["impact"]


async def test_init_will_not_produce_a_declaration_with_no_fields(git_repo, monkeypatch):
    monkeypatch.delenv(schema.SCHEMA_ENV, raising=False)
    setup = FieldSetupApp()
    async with setup.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(setup.screen, FieldsScreen), "收不下，留在原地"


# --- 唯讀：看得到，改不了 ---


async def test_read_only_refuses_to_start_editing(controller, git_repo, commit):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master", read_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert app.editing is False


async def test_read_only_refuses_the_default_fill(controller, git_repo, commit):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master", read_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_read_only_refuses_the_settings_screens(controller, git_repo, commit):
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master", read_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert not isinstance(app.screen, FieldsScreen)
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert not isinstance(app.screen, DefaultNoteScreen)


async def test_read_only_still_lets_you_look_around(controller, git_repo, commit):
    """唯讀不是把功能拿掉：換區間、看 commit 資訊都還在。"""
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master", read_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert isinstance(app.screen, RangeScreen)


async def test_the_shortcut_list_says_why_those_keys_do_nothing(controller, git_repo, commit):
    """按了才發現做不了，不如在清單上就看得出來。"""
    base = commit("feat: base")
    commit("feat: 一")
    app = editor(controller, f"{base}...master", read_only=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.unavailable_keys()["request_save"] == app.READ_ONLY_REASON
