"""增修欄位只需要改宣告檔——這件事對每一個消費端都要成立。

在宣告檔裡加一個欄位，不改任何 Python，確認驗證、TUI 表單、CLI 旗標、文字與 JSON
輸出、xlsx 表頭全部跟著出現。
"""

import json

import pytest
from textual.app import App, ComposeResult

from gne import cli, export, render
from gne.core import schema
from gne.tui.widgets import NotePrompt

TRIAL_KEY = "trial_field"
TRIAL_FLAG = "--trial-field"
TRIAL_HEADER = "trial field"
TRIAL_DECLARATION = {
    "title": "試驗欄位",
    "type": "string",
    "x-input": "text",
    "x-prompt": "只在這個測試裡存在的欄位。",
}


def _reset_caches() -> None:
    schema.load_schema.cache_clear()
    schema.note_fields.cache_clear()
    schema.field_by_key.cache_clear()
    schema._note_validator.cache_clear()


@pytest.fixture
def declared_trial_field(tmp_path, monkeypatch):
    document = json.loads(schema.EXAMPLE_PATH.read_text(encoding="utf-8"))
    document["properties"][TRIAL_KEY] = TRIAL_DECLARATION
    path = tmp_path / "note-schema.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(schema.SCHEMA_ENV, str(path))
    _reset_caches()
    yield
    _reset_caches()


class PromptHost(App[None]):
    def compose(self) -> ComposeResult:
        yield NotePrompt()


def test_the_baseline_declaration_has_no_trial_field():
    assert TRIAL_KEY not in schema.field_by_key()


def test_the_new_field_reaches_the_field_table(declared_trial_field):
    assert schema.field_by_key()[TRIAL_KEY].title == "試驗欄位"


def flags_of(*path: str) -> set[str]:
    """走進巢狀的子命令，收那一層掛著的旗標。"""
    parser = cli.build_parser()
    for name in path:
        parser = parser._subparsers._group_actions[0].choices[name]
    return {option for action in parser._actions for option in action.option_strings}


def test_the_new_field_reaches_the_cli_flags(declared_trial_field):
    assert TRIAL_FLAG in flags_of("note", "set")


def test_the_new_field_reaches_the_schema_listing(declared_trial_field):
    assert TRIAL_KEY in render.schema_as_text()


def test_the_new_field_reaches_the_spreadsheet_header(declared_trial_field):
    header = next(export.build_workbook([]).active.values)
    assert TRIAL_HEADER in header


def test_the_new_field_reaches_the_text_rendering(declared_trial_field):
    assert "試驗欄位: 有值" in render.note_as_text({"type": "feat", TRIAL_KEY: "有值"})


async def test_the_new_field_gets_asked_by_the_editor(declared_trial_field):
    """問答的題目也是從宣告檔衍生的：新欄位會被問到，順序照宣告。"""
    async with PromptHost().run_test(size=(80, 40)) as pilot:
        prompt = pilot.app.query_one(NotePrompt)
        prompt.start({})
        await pilot.pause()
        asked = []
        while prompt.asking:
            asked.append(prompt.current_field.key)
            await pilot.press("enter")
            await pilot.pause()
        assert TRIAL_KEY in asked
        assert asked == [field.key for field in schema.note_fields()]


def capsys_free_show():
    from gne.core.entity import NoteController

    return NoteController({"schematic": "yaml", "fetch": False, "push": False}).show()


def test_the_new_field_can_be_written_and_read_back(declared_trial_field, git_repo, commit, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_FETCH", False)
    commit()
    assert cli.main(["--no-push", "note", "set", "--type", "feat", TRIAL_FLAG, "寫進去了"]) == 0
    assert cli.main(["--no-push", "note", "show", "--format", "json"]) == 0
    written = capsys_free_show()
    assert written[TRIAL_KEY] == "寫進去了"


def test_a_value_for_an_undeclared_field_is_refused(git_repo, commit, monkeypatch):
    """宣告檔沒有的欄位不能悄悄存進去——additionalProperties: false 就是為此。"""
    monkeypatch.setattr(cli, "DEFAULT_FETCH", False)
    commit()
    with pytest.raises(schema.NoteValidationError):
        schema.validate_note({"type": "feat", TRIAL_KEY: "沒宣告過"})
