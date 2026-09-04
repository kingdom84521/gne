import json

import pytest

from gne import render


def row(commit="a" * 40, subject="feat: 做了東西", author="Someone", date="2026-01-01", note=None):
    return {"commit": commit, "subject": subject, "author": author, "date": date, "note": note}


# --- 單筆 note 的三種格式 ---


def test_text_uses_chinese_titles():
    text = render.note_as_text({"type": "feat", "change_log": "做了東西"})
    assert "變更種類" in text
    assert "功能" in text
    assert "變更說明" in text


def test_text_renders_redmine_ids_as_urls():
    text = render.note_as_text({"type": "fix", "redmine_ids": [7788]})
    assert "https://redmine.example.com/issues/7788" in text


def test_text_omits_empty_fields():
    text = render.note_as_text({"type": "skip", "change_log": "", "redmine_ids": []})
    assert "變更說明" not in text
    assert "識別碼" not in text


def test_text_survives_a_type_value_the_schema_does_not_know():
    """舊資料裡真的有 type: ''，呈現層不能因為查不到標籤就當掉。"""
    text = render.note_as_text({"type": ""})
    assert text is not None


def test_text_survives_an_unexpected_type_value():
    text = render.note_as_text({"type": "brand-new-kind"})
    assert "brand-new-kind" in text


def test_text_survives_a_missing_type():
    assert render.note_as_text({"change_log": "只有說明"}) is not None


def test_text_survives_an_unknown_field():
    text = render.note_as_text({"type": "feat", "mystery": "看不懂的東西"})
    assert "看不懂的東西" in text


def test_json_is_faithful_and_does_not_invent_fields():
    document = {"type": "feat", "change_log": "x"}
    assert json.loads(render.note_as_json(document)) == document


def test_json_keeps_unicode_readable():
    assert "修好了" in render.note_as_json({"type": "fix", "change_log": "修好了"})


def test_yaml_round_trips_through_the_stored_form():
    document = {"type": "fix", "change_log": "多行\n說明"}
    assert render.parse_note(render.note_as_yaml(document), "yaml") == document


def test_json_round_trips():
    document = {"type": "fix", "change_log": "多行\n說明", "redmine_ids": [1]}
    assert render.parse_note(render.note_as_json(document), "json") == document


@pytest.mark.parametrize("payload", ["", "   ", "\n"])
def test_parsing_empty_input_is_refused(payload):
    with pytest.raises(render.InputError):
        render.parse_note(payload, "yaml")


@pytest.mark.parametrize("payload", ["just a string", "- a\n- b", "123"])
def test_parsing_a_non_mapping_is_refused(payload):
    with pytest.raises(render.InputError):
        render.parse_note(payload, "yaml")


def test_parsing_malformed_yaml_is_refused():
    with pytest.raises(render.InputError):
        render.parse_note("type: [unclosed", "yaml")


def test_parsing_malformed_json_is_refused():
    with pytest.raises(render.InputError):
        render.parse_note('{"type": ', "json")


# --- 區間列表 ---


def test_unnoted_text_row_matches_hash_then_author():
    """一行就是 hash 接作者，中間兩個空白，作者不帶引號。"""
    text = render.rows_as_text([row(commit="b" * 40, author="pat_lee")])
    assert text == f"{'b' * 40}  pat_lee"


def test_author_is_not_wrapped_in_quotes():
    text = render.rows_as_text([row(author="pat_lee")])
    assert "'pat_lee'" not in text


def test_noted_row_shows_the_note_indented_underneath():
    text = render.rows_as_text([row(note={"type": "feat", "change_log": "做了東西"})])
    lines = text.splitlines()
    assert lines[0].startswith("a" * 40)
    assert any(line.startswith("    ") and "功能" in line for line in lines[1:])


def test_rows_as_json_carries_commit_metadata_and_the_note():
    payload = json.loads(render.rows_as_json([row(note={"type": "skip"})]))
    assert payload == [
        {
            "commit": "a" * 40,
            "subject": "feat: 做了東西",
            "author": "Someone",
            "date": "2026-01-01",
            "note": {"type": "skip"},
        }
    ]


def test_rows_as_json_uses_null_for_a_commit_without_a_note():
    payload = json.loads(render.rows_as_json([row()]))
    assert payload[0]["note"] is None


def test_empty_listing_renders_as_empty_string_not_a_crash():
    assert render.rows_as_text([]) == ""
    assert json.loads(render.rows_as_json([])) == []


# --- schema 自述 ---


def test_schema_as_text_lists_every_field_with_its_input_kind():
    text = render.schema_as_text()
    for key in ("type", "change_log", "redmine_ids", "spec_change", "data_migration"):
        assert key in text
    assert "feat" in text and "skip" in text


def test_schema_as_text_carries_the_filling_prompt():
    """`gne schema` 是拿得到填寫指示的地方——欄位標題本身說不出怎麼填。"""
    text = render.schema_as_text()
    assert "skip 是預設答案" in text
    assert "不要照抄 commit message" in text


def test_schema_as_text_marks_the_fields_ai_may_not_fill():
    text = render.schema_as_text()
    headline = next(line for line in text.splitlines() if line.startswith("spec_change"))
    assert "人工填寫" in headline


def test_schema_as_text_does_not_mark_the_others_as_human_only():
    text = render.schema_as_text()
    headline = next(line for line in text.splitlines() if line.startswith("change_log"))
    assert "人工填寫" not in headline


# --- AI 產生的備註 ---


AI_NOTE = {"type": "fix", "change_log": "AI 寫的說明", "ai_generated": True}


def test_text_says_a_note_is_waiting_for_a_human():
    assert render.AI_NOTICE in render.note_as_text(AI_NOTE)


def test_the_notice_comes_before_the_fields_it_warns_about():
    assert render.note_as_text(AI_NOTE).splitlines()[0].startswith(render.AI_NOTICE)


def test_text_never_prints_the_marker_as_a_field():
    assert "ai_generated" not in render.note_as_text(AI_NOTE)


def test_text_of_a_human_note_carries_no_notice():
    assert render.AI_NOTICE not in render.note_as_text({"type": "fix"})


def test_an_older_mapping_marker_still_produces_a_notice():
    """先前的記號是一個 mapping，真值判讀讓那些備註照樣看得出來。"""
    older = {"type": "fix", "ai_generated": {"fields": ["type"]}}
    assert render.AI_NOTICE in render.note_as_text(older)


def test_schema_as_text_says_which_fields_skip_stops_asking():
    headline = next(
        line for line in render.schema_as_text().splitlines() if line.startswith("change_log")
    )
    assert "變更種類 是 skip 時不問" in headline
