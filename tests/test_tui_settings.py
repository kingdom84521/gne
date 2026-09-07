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
from gne.tui.screens.fields import FieldFormScreen

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
    target.write_text(schema.TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
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
