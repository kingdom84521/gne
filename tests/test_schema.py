import json

import pytest
from jsonschema.exceptions import SchemaError

from gne.core import schema


def test_fields_follow_declaration_order():
    assert [field.key for field in schema.note_fields()] == [
        "type",
        "change_log",
        "redmine_ids",
        "spec_change",
        "data_migration",
    ]


def test_only_type_is_required():
    required = {field.key for field in schema.note_fields() if field.required}
    assert required == {"type"}


def test_choice_labels_come_from_declaration():
    type_field = schema.field_by_key()["type"]
    assert type_field.choice_labels == {
        "feat": "功能",
        "fix": "錯誤",
        "security": "安全性",
        "skip": "略過",
    }


def test_cli_flags_are_derived_from_keys():
    assert [field.cli_flag for field in schema.note_fields()] == [
        "--type",
        "--change-log",
        "--redmine-ids",
        "--spec-change",
        "--data-migration",
    ]


def test_redmine_item_url_comes_from_declaration():
    field = schema.field_by_key()["redmine_ids"]
    assert field.format_item(12345).endswith("/issues/12345")


@pytest.mark.parametrize(
    "document",
    [
        {"type": "skip"},
        {"type": "feat", "change_log": "新增了東西"},
        {"type": "fix", "redmine_ids": [1, 2]},
        {"type": "security", "spec_change": "", "data_migration": ""},
    ],
)
def test_valid_notes_pass(document):
    schema.validate_note(document)


@pytest.mark.parametrize(
    ("document", "expected_hint"),
    [
        ({}, "type"),
        ({"type": "bogus"}, "bogus"),
        ({"type": "skip", "unknown_field": "x"}, "unknown_field"),
        ({"type": "skip", "redmine_ids": ["not-an-int"]}, "not-an-int"),
        ({"type": "skip", "change_log": 42}, "42"),
    ],
)
def test_invalid_notes_are_rejected(document, expected_hint):
    with pytest.raises(schema.NoteValidationError) as caught:
        schema.validate_note(document)
    assert expected_hint in str(caught.value)


# --- 宣告檔本身寫錯時要當場報錯，不能靜默失效 ---


def _declaration(**type_extras):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["type"],
        "properties": {
            "type": {
                "title": "變更種類",
                "type": "string",
                "enum": ["feat", "skip"],
                "x-prompt": "怎麼填這個欄位。",
                **type_extras,
            }
        },
    }


def test_misspelled_extension_keyword_is_rejected():
    document = _declaration(**{"x-inputt": "choice", "x-choice-labels": {}})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "x-inputt" in str(caught.value)


def test_choice_without_labels_is_rejected():
    document = _declaration(**{"x-input": "choice"})
    with pytest.raises(schema.SchemaDeclarationError):
        schema.build_fields(document)


def test_choice_labels_must_cover_every_enum_value():
    document = _declaration(**{"x-input": "choice", "x-choice-labels": {"feat": "功能"}})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "skip" in str(caught.value)


def test_choice_labels_may_not_invent_values():
    document = _declaration(
        **{
            "x-input": "choice",
            "x-choice-labels": {"feat": "功能", "skip": "略過", "ghost": "幽靈"},
        }
    )
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "ghost" in str(caught.value)


def test_item_url_on_a_non_list_field_is_rejected():
    document = _declaration(
        **{"x-input": "choice", "x-choice-labels": {"feat": "功能", "skip": "略過"},
           "x-item-url": "https://example.com/{value}"}
    )
    with pytest.raises(schema.SchemaDeclarationError):
        schema.build_fields(document)


def test_invalid_json_schema_is_rejected(tmp_path):
    broken = tmp_path / "note-schema.json"
    broken.write_text(json.dumps({"type": "object", "properties": {"a": {"type": 123}}}))
    with pytest.raises(SchemaError):
        schema.read_schema(broken)


# --- 資料保存規則：只有「每個欄位都空」的 note 可以移除 ---


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"type": ""},
        {"type": "", "change_log": "", "redmine_ids": [], "spec_change": "", "data_migration": ""},
        {"type": "   ", "change_log": "\n"},
    ],
)
def test_blank_notes_are_recognised(document):
    assert schema.is_blank_note(document) is True


@pytest.mark.parametrize(
    "document",
    [
        {"type": "skip"},
        {"type": "skip", "change_log": "", "redmine_ids": [], "spec_change": "", "data_migration": ""},
        {"type": "", "change_log": "有東西"},
        {"type": "", "redmine_ids": [123]},
        {"type": "", "spec_change": "規格動了"},
    ],
)
def test_notes_with_any_content_are_never_blank(document):
    assert schema.is_blank_note(document) is False


def test_unknown_keys_make_a_note_non_blank():
    """看不懂的內容一律不判定為可移除。"""
    assert schema.is_blank_note({"type": "", "mystery": "資料"}) is False
    assert schema.is_blank_note({"type": "", "mystery": ""}) is False


def test_strip_empty_drops_only_empty_values():
    assert schema.strip_empty(
        {"type": "feat", "change_log": "", "redmine_ids": [], "spec_change": "x"}
    ) == {"type": "feat", "spec_change": "x"}


def test_a_field_without_a_prompt_is_rejected():
    """沒有填寫指示的欄位沒人填得出來——AI 沒有指示，人也只看得到標題。"""
    document = _declaration()
    del document["properties"]["type"]["x-prompt"]
    document["properties"]["type"].update({"x-input": "choice", "x-choice-labels": {"feat": "功能", "skip": "略過"}})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "x-prompt" in str(caught.value)


def test_a_blank_prompt_is_rejected():
    document = _declaration(**{"x-prompt": "   ", "x-input": "text"})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "x-prompt" in str(caught.value)


def test_every_declared_field_carries_a_prompt():
    assert all(field.prompt.strip() for field in schema.note_fields())


def test_the_human_only_fields_are_declared_as_such():
    """AI 不能代填的那兩個。這是宣告，不是靠 prompt 拜託。"""
    human_only = {field.key for field in schema.note_fields() if field.human_only}
    assert human_only == {"spec_change", "data_migration"}


def test_human_only_defaults_to_false():
    document = _declaration(**{"x-input": "text"})
    assert schema.build_fields(document)[0].human_only is False


def test_a_note_carrying_only_an_ai_marker_is_never_pruned():
    """prune 只移除什麼都沒有的備註。看不懂的內容一律留著，記號也算。"""
    assert schema.is_blank_note({"type": "", "ai_generated": True}) is False


def test_a_value_outside_the_choices_is_refused_when_it_is_typed():
    """CLI 旗標與 TUI 問答共用 parse_value，所以兩邊都在當下就說清楚，
    而不是等到寫入時才由 jsonschema 丟一句難讀的訊息。"""
    field = schema.field_by_key()["type"]
    with pytest.raises(schema.FieldInputError) as caught:
        schema.parse_value(field, "not-a-kind")
    assert "not-a-kind" in str(caught.value)
    assert "feat / fix / security / skip" in str(caught.value)


def test_every_declared_choice_is_accepted():
    field = schema.field_by_key()["type"]
    for choice in field.choices:
        assert schema.parse_value(field, choice) == choice


def test_an_empty_answer_clears_a_choice_field():
    """空的答案是「這一欄留白」，不是不合法的選項。"""
    assert schema.parse_value(schema.field_by_key()["type"], "") == ""


def test_a_partial_note_may_omit_required_fields():
    schema.validate_partial({"change_log": "只有說明"})
    schema.validate_partial({})


def test_a_partial_note_still_has_to_use_declared_fields_and_values():
    with pytest.raises(schema.NoteValidationError):
        schema.validate_partial({"typo_field": "x"})
    with pytest.raises(schema.NoteValidationError):
        schema.validate_partial({"type": "not-a-kind"})


def test_writing_still_requires_the_required_fields():
    """部分驗證只用在起點上；真的要寫進 refs/notes 時規則不變。"""
    with pytest.raises(schema.NoteValidationError):
        schema.validate_note({"change_log": "沒有 type"})


# --- 被前面的答案決定掉的欄位 ---


def test_the_declaration_says_which_fields_skip_stops_asking():
    stopped = {field.key for field in schema.note_fields() if field.ignore_when}
    assert stopped == {"change_log", "redmine_ids", "spec_change", "data_migration"}
    assert schema.field_by_key()["change_log"].ignore_when == {"type": "skip"}


def test_a_field_is_ignored_only_when_the_condition_holds():
    field = schema.field_by_key()["change_log"]
    assert schema.ignored(field, {"type": "skip"}) is True
    assert schema.ignored(field, {"type": "fix"}) is False
    assert schema.ignored(field, {}) is False


def test_a_field_without_a_condition_is_always_asked():
    assert schema.ignored(schema.field_by_key()["type"], {"type": "skip"}) is False


def test_the_reason_reads_in_the_declared_titles():
    assert schema.ignore_reason(schema.field_by_key()["change_log"]) == "變更種類 是 skip"


def test_a_condition_naming_a_field_that_does_not_exist_is_rejected():
    """條件寫錯的欄位名要當場報錯，不能靜靜地永遠不成立。"""
    document = _declaration(**{"x-input": "text", "x-ignore-when": {"typo_field": "skip"}})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "typo_field" in str(caught.value)


# --- 跟著 commit convention 走 ---


def test_the_declaration_says_which_field_follows_the_convention():
    following = {field.key for field in schema.note_fields() if field.follow_convention}
    assert following == {"type"}


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("fix: 修好了", "fix"),
        ("fix(i18n): 帶 scope", "fix"),
        ("chore: 雜事", "chore"),
        ("沒有冒號", ""),
        ("", ""),
    ],
)
def test_the_convention_prefix_ignores_the_scope(subject, expected):
    assert schema.from_convention(subject) == expected


def test_following_the_convention_needs_something_to_match_against():
    """對照的對象就是那組可選值，沒有可選值就無從對起。"""
    document = _declaration(**{"x-input": "text", "x-follow-convention": True})
    with pytest.raises(schema.SchemaDeclarationError) as caught:
        schema.build_fields(document)
    assert "x-follow-convention" in str(caught.value)


# --- 宣告檔屬於專案，不屬於 gne ---


def test_the_declaration_is_looked_for_in_the_repo(git_repo, monkeypatch):
    monkeypatch.delenv(schema.SCHEMA_ENV, raising=False)
    assert schema.schema_path() == git_repo / ".gne" / "note-schema.json"


def test_the_environment_variable_wins(tmp_path, monkeypatch):
    elsewhere = tmp_path / "somewhere" / "fields.json"
    monkeypatch.setenv(schema.SCHEMA_ENV, str(elsewhere))
    assert schema.schema_path() == elsewhere


def test_a_repo_without_a_declaration_says_so(git_repo, monkeypatch):
    """套件裡的範本不是預設值：拿別人的欄位當預設，比講不出話更難發現。"""
    monkeypatch.delenv(schema.SCHEMA_ENV, raising=False)
    schema.load_schema.cache_clear()
    with pytest.raises(schema.SchemaNotDeclared):
        schema.load_schema()
    schema.load_schema.cache_clear()


def test_the_template_ships_with_the_package_and_is_a_valid_declaration():
    assert schema.TEMPLATE_PATH.is_file()
    assert schema.build_fields(schema.read_schema(schema.TEMPLATE_PATH))
