"""新備註的起點：.gne/default-note。"""

import pytest

from conftest import run_git, write_default_note
from gne.core import defaults, schema


write_default = write_default_note


def test_without_the_file_there_is_no_default(git_repo):
    assert defaults.default_note() == {}


def test_the_file_supplies_the_starting_point(git_repo):
    write_default(git_repo, "type: skip\n")
    assert defaults.default_note() == {"type": "skip"}


def test_comments_and_blank_lines_are_fine(git_repo):
    write_default(git_repo, "# 一筆新備註的起點\n\ntype: skip\n")
    assert defaults.default_note() == {"type": "skip"}


def test_an_empty_file_is_no_default_rather_than_an_error(git_repo):
    write_default(git_repo, "# 什麼都沒設\n")
    assert defaults.default_note() == {}


def test_a_field_the_schema_never_declared_is_refused(git_repo):
    """預設值寫錯要在這裡就被擋下來，而不是等到寫某一筆備註時才炸。"""
    write_default(git_repo, "typo_field: x\n")
    with pytest.raises(schema.NoteValidationError):
        defaults.default_note()


def test_a_value_the_schema_refuses_is_refused_here_too(git_repo):
    write_default(git_repo, "type: not-a-kind\n")
    with pytest.raises(schema.NoteValidationError) as caught:
        defaults.default_note()
    assert "not-a-kind" in str(caught.value)


def test_a_file_that_is_not_a_mapping_is_refused(git_repo):
    write_default(git_repo, "- 一串清單\n")
    with pytest.raises(schema.NoteValidationError):
        defaults.default_note()


def test_the_file_sits_beside_the_field_declaration(git_repo):
    """與 .gne/note-schema.json 同一個目錄：兩者都是這個 repo 對 gne 說的話。"""
    assert defaults.default_note_path().name == "default-note"
    assert defaults.default_note_path().parent.name == ".gne"


def test_outside_a_repository_there_is_no_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert defaults.default_note() == {}
    assert run_git
