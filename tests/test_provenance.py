"""出處記號：這一筆是不是 AI 寫的。"""

import pytest
import yaml

from gne.core import provenance, schema


def test_a_note_nobody_marked_has_no_marker():
    assert provenance.is_ai_generated({"type": "fix"}) is False


def test_stamping_marks_the_note_without_naming_fields():
    """記號只回答「是不是 AI 寫的」。哪幾欄由誰填不必記——審閱是逐筆看整份。"""
    stamped = provenance.stamped({"type": "fix", "change_log": "AI 寫的"}, ["type", "change_log"])
    assert stamped["ai_generated"] is True
    assert provenance.is_ai_generated(stamped) is True


def test_stamping_leaves_the_fields_exactly_as_they_were():
    document = {"type": "fix", "redmine_ids": [7]}
    assert provenance.fields_of(provenance.stamped(document, ["type", "redmine_ids"])) == document


def test_the_marker_survives_yaml():
    stamped = provenance.stamped({"type": "fix"}, ["type"])
    assert yaml.safe_load(yaml.safe_dump(stamped, allow_unicode=True)) == stamped


def test_writing_only_empty_values_marks_nothing():
    assert provenance.stamped({"change_log": ""}, ["change_log"]) == {"change_log": ""}


def test_a_write_that_fills_something_marks_the_note():
    stamped = provenance.stamped({"type": "fix", "change_log": ""}, ["type", "change_log"])
    assert stamped["ai_generated"] is True


@pytest.mark.parametrize("key", ["spec_change", "data_migration"])
def test_a_human_only_field_cannot_be_stamped(key):
    with pytest.raises(schema.FieldInputError) as caught:
        provenance.stamped({key: "人才知道"}, [key])
    assert caught.value.field_key == key


def test_clearing_drops_the_marker_and_nothing_else():
    stamped = provenance.stamped({"type": "fix", "change_log": "說明"}, ["type"])
    assert provenance.cleared(stamped) == {"type": "fix", "change_log": "說明"}


def test_clearing_a_note_without_a_marker_changes_nothing():
    assert provenance.cleared({"type": "fix"}) == {"type": "fix"}


@pytest.mark.parametrize(
    "raw",
    [True, "yes", 1, {"at": "2026-09-01T16:20:00+08:00", "fields": ["type"]}],
)
def test_anything_truthy_counts_as_ai_written(raw):
    """先前的記號是一個 mapping。真值判讀讓那些備註照樣被認出來。"""
    assert provenance.is_ai_generated({"type": "fix", "ai_generated": raw}) is True


@pytest.mark.parametrize("raw", [False, None, "", 0, {}])
def test_a_falsy_marker_is_not_ai_written(raw):
    assert provenance.is_ai_generated({"type": "fix", "ai_generated": raw}) is False


def test_the_marker_is_never_part_of_the_validated_document():
    stamped = provenance.stamped({"type": "fix"}, ["type"])
    schema.validate_note(provenance.fields_of(stamped))
    with pytest.raises(schema.NoteValidationError):
        schema.validate_note(stamped)


def test_a_misspelled_marker_is_caught_as_an_undeclared_field():
    """記號名字打錯就不是記號了，additionalProperties: false 會擋下來。"""
    with pytest.raises(schema.NoteValidationError):
        schema.validate_note(provenance.fields_of({"type": "fix", "ai_genrated": {}}))
