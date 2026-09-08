import json

import pytest

from conftest import run_git
from gne import cli
from gne.core import git, schema
from gne.tui.screens.fields import FieldPlan


@pytest.fixture
def no_remote(monkeypatch):
    """測試 repo 沒有 origin：強迫每個指令都走 --no-push 且不 fetch。"""
    monkeypatch.setattr(cli, "DEFAULT_FETCH", False)


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(cli, "interactive_possible", lambda: False)


def run(*arguments, expect=0):
    code = cli.main(["--no-push", *arguments])
    assert code == expect, f"預期 exit {expect}，實際 {code}"
    return code


# --- 子命令派發與舊用法 ---


@pytest.fixture
def spy_editor(monkeypatch):
    """攔下編輯器的啟動參數，不真的開 TUI。"""
    seen: dict = {}
    monkeypatch.setattr(cli, "interactive_possible", lambda: True)
    monkeypatch.setattr(cli, "run_editor", lambda controller, **arguments: seen.update(arguments))
    return seen


def test_a_bare_invocation_lists_your_own_unfilled_commits(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main([])
    assert spy_editor.get("only") is None
    assert spy_editor["author_email"] == "test@example.com"
    assert spy_editor["unnoted_only"] is True


def test_a_bare_hash_still_opens_that_one_commit(git_repo, commit, no_remote, spy_editor):
    first = commit()
    commit()
    cli.main([first])
    assert spy_editor["only"] == first


def test_all_authors_drops_the_author_filter(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--all-authors"])
    assert spy_editor["author_email"] is None


def test_a_named_author_is_passed_through(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--author", "someone@example.com"])
    assert spy_editor["author_email"] == "someone@example.com"


def test_include_noted_widens_the_listing(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--include-noted"])
    assert spy_editor["unnoted_only"] is False


def test_no_push_reaches_the_editor(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--no-push"])
    assert spy_editor["push"] is False


def test_an_unknown_hash_is_refused_before_the_editor_starts(git_repo, commit, no_remote, spy_editor, capsys):
    commit()
    assert cli.main(["definitely-not-a-hash-0000000"]) != 0
    assert spy_editor == {}


def test_an_unknown_subcommand_is_rejected(git_repo, commit, no_remote, headless):
    commit()
    assert cli.main(["definitely-not-a-subcommand-nor-a-hash"]) != 0


# --- 沒有終端機時不能卡住等輸入 ---


def test_the_editor_refuses_to_start_without_a_terminal(git_repo, commit, no_remote, headless, capsys):
    commit()
    assert cli.main([]) != 0
    assert "gne note show" in capsys.readouterr().err


def test_the_headless_message_points_at_the_non_interactive_commands(
    git_repo, commit, no_remote, headless, capsys
):
    commit()
    cli.main([])
    complaint = capsys.readouterr().err
    assert "gne note set" in complaint


# --- show ---


def test_show_prints_the_note(git_repo, commit, no_remote, capsys):
    head = commit()
    run("note", "set", head, "--type", "feat", "--change-log", "做了東西")
    run("note", "show", head)
    assert "做了東西" in capsys.readouterr().out


def test_show_defaults_to_head(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "skip")
    run("note", "show")
    assert "略過" in capsys.readouterr().out


def test_show_as_json_is_parseable(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "fix", "--change-log", "修好了")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {"type": "fix", "change_log": "修好了"}


def test_show_as_yaml_round_trips_back_in(git_repo, commit, no_remote, capsys, monkeypatch):
    head = commit()
    run("note", "set", "--type", "fix", "--change-log", "多行\n說明")
    run("note", "show", "--format", "yaml")
    stored = capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", _Stdin(stored))
    run("note", "set", head, "--from-stdin", "--format", "yaml")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out)["change_log"] == "多行\n說明"


def test_show_without_a_note_exits_non_zero(git_repo, commit, no_remote, capsys):
    commit()
    assert cli.main(["--no-push", "note", "show"]) != 0
    assert capsys.readouterr().err.strip()


def test_show_on_an_unknown_hash_exits_non_zero_without_a_traceback(
    git_repo, commit, no_remote, capsys
):
    commit()
    assert cli.main(["--no-push", "note", "show", "definitely-not-a-ref"]) != 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert captured.err.strip()


# --- set ---


class _Stdin:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self) -> str:
        return self._payload

    def isatty(self) -> bool:
        return False


def test_set_writes_only_the_given_fields(git_repo, commit, no_remote, capsys):
    head = commit()
    run("note", "set", head, "--type", "feat", "--change-log", "第一版")
    run("note", "set", head, "--change-log", "第二版")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {"type": "feat", "change_log": "第二版"}


def test_set_with_an_empty_value_clears_that_field(git_repo, commit, no_remote, capsys):
    head = commit()
    run("note", "set", head, "--type", "feat", "--change-log", "會被清掉")
    run("note", "set", head, "--change-log", "")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {"type": "feat"}


def test_set_accepts_comma_separated_redmine_ids(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "fix", "--redmine-ids", "101,102")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out)["redmine_ids"] == [101, 102]


def test_set_rejects_non_numeric_redmine_ids(git_repo, commit, no_remote):
    commit()
    assert cli.main(["--no-push", "note", "set", "--type", "fix", "--redmine-ids", "abc"]) != 0


def test_set_rejects_a_type_outside_the_schema(git_repo, commit, no_remote, capsys):
    commit()
    assert cli.main(["--no-push", "note", "set", "--type", "not-a-kind"]) != 0
    assert "not-a-kind" in capsys.readouterr().err


def test_set_with_no_fields_at_all_is_refused(git_repo, commit, no_remote, capsys):
    commit()
    assert cli.main(["--no-push", "note", "set"]) != 0
    assert capsys.readouterr().err.strip()


def test_set_from_empty_stdin_is_refused(git_repo, commit, no_remote, monkeypatch, capsys):
    commit()
    monkeypatch.setattr("sys.stdin", _Stdin("   \n"))
    assert cli.main(["--no-push", "note", "set", "--from-stdin"]) != 0
    assert capsys.readouterr().err.strip()


def test_set_from_malformed_stdin_is_refused(git_repo, commit, no_remote, monkeypatch):
    commit()
    monkeypatch.setattr("sys.stdin", _Stdin("type: [unclosed"))
    assert cli.main(["--no-push", "note", "set", "--from-stdin"]) != 0


def test_set_from_stdin_replaces_the_whole_note(git_repo, commit, no_remote, monkeypatch, capsys):
    head = commit()
    run("note", "set", head, "--type", "feat", "--spec-change", "會消失")
    monkeypatch.setattr("sys.stdin", _Stdin('{"type": "fix"}'))
    run("note", "set", head, "--from-stdin", "--format", "json")
    run("note", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {"type": "fix"}


def test_set_cannot_mix_stdin_with_field_flags(git_repo, commit, no_remote, monkeypatch):
    commit()
    monkeypatch.setattr("sys.stdin", _Stdin('{"type": "fix"}'))
    assert cli.main(["--no-push", "note", "set", "--from-stdin", "--type", "feat"]) != 0


# --- list ---


def test_list_unnoted_matches_hash_then_author(git_repo, commit, no_remote, capsys):
    base = commit("feat: base")
    later = commit("feat: later", author="pat_lee <pat@example.com>")
    run("list", f"{base}...master", "--filter", "unnoted")
    assert capsys.readouterr().out.strip() == f"{later}  pat_lee"


def test_list_prints_the_count_on_stderr_so_stdout_stays_pipeable(
    git_repo, commit, no_remote, capsys
):
    base = commit()
    commit()
    run("list", f"{base}...master", "--filter", "unnoted")
    captured = capsys.readouterr()
    assert "1" in captured.err
    assert captured.err not in captured.out


def test_list_noted_only(git_repo, commit, no_remote, capsys):
    base = commit()
    noted = commit()
    commit()
    run("note", "set", noted, "--type", "feat")
    run("list", f"{base}...master", "--filter", "noted")
    output = capsys.readouterr().out
    assert noted in output
    assert output.count("\n") >= 1


def test_list_json_carries_every_field_the_export_needs(git_repo, commit, no_remote, capsys):
    base = commit()
    head = commit("fix: 修好了")
    run("note", "set", head, "--type", "fix", "--change-log", "說明", "--redmine-ids", "9")
    run("list", f"{base}...master", "--format", "json")
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["commit"] == head
    assert payload[0]["subject"] == "fix: 修好了"
    assert payload[0]["author"]
    assert payload[0]["date"]
    assert payload[0]["note"]["redmine_ids"] == [9]


def test_list_on_an_invalid_range_exits_cleanly(git_repo, commit, no_remote, capsys):
    commit()
    assert cli.main(["--no-push", "list", "nonsense...alsononsense"]) != 0
    assert "Traceback" not in capsys.readouterr().err


def test_list_of_an_empty_range_is_not_an_error(git_repo, commit, no_remote, capsys):
    head = commit()
    run("list", f"{head}...master")
    assert capsys.readouterr().out.strip() == ""


# --- schema ---


def test_schema_json_is_the_declaration_itself(git_repo, commit, no_remote, capsys):
    commit()
    run("schema", "show", "--format", "json")
    assert json.loads(capsys.readouterr().out)["properties"]["type"]["enum"] == [
        "feat", "fix", "security", "skip"
    ]


def test_schema_text_lists_the_flags(git_repo, commit, no_remote, capsys):
    commit()
    run("schema", "show")
    assert "--change-log" in capsys.readouterr().out


# --- remove ---


def test_remove_deletes_the_note(git_repo, commit, no_remote):
    head = commit()
    run("note", "set", "--type", "skip")
    run("note", "remove", head)
    assert git.notes_list() == {}


def test_remove_without_a_note_exits_non_zero(git_repo, commit, no_remote):
    commit()
    assert cli.main(["--no-push", "note", "remove"]) != 0


# --- backup 與 prune ---


def test_backup_lists_notes_that_carry_content(git_repo, commit, no_remote, capsys):
    head = commit()
    run("note", "set", "--type", "feat", "--change-log", "要保留的內容")
    run("note", "backup")
    output = capsys.readouterr().out
    assert head in output
    assert "要保留的內容" in output


def test_backup_omits_blank_notes(git_repo, commit, no_remote, capsys):
    blank = commit()
    git.notes_add(blank, "type: ''", force=False)
    run("note", "backup")
    assert blank not in capsys.readouterr().out


def test_prune_dry_run_reports_without_removing(git_repo, commit, no_remote, capsys):
    blank = commit()
    git.notes_add(blank, "type: ''\nchange_log: ''", force=False)
    run("note", "prune")
    assert blank in capsys.readouterr().out
    assert blank in git.notes_list()


def test_prune_apply_requires_explicit_confirmation(git_repo, commit, no_remote, capsys):
    blank = commit()
    git.notes_add(blank, "type: ''", force=False)
    assert cli.main(["--no-push", "note", "prune", "--apply"]) != 0
    assert blank in git.notes_list()
    assert "--yes" in capsys.readouterr().err


def test_prune_apply_removes_only_blank_notes(git_repo, commit, no_remote):
    blank = commit()
    kept_skip = commit()
    kept_content = commit()
    git.notes_add(blank, "type: ''\nchange_log: ''", force=False)
    git.notes_add(kept_skip, "type: skip", force=False)
    git.notes_add(kept_content, "type: ''\nchange_log: 有東西", force=False)
    run("note", "prune", "--apply", "--yes")
    remaining = git.notes_list()
    assert blank not in remaining
    assert kept_skip in remaining
    assert kept_content in remaining


def test_prune_leaves_notes_with_unknown_fields_alone(git_repo, commit, no_remote):
    mystery = commit()
    git.notes_add(mystery, "type: ''\nmystery: ''", force=False)
    run("note", "prune", "--apply", "--yes")
    assert mystery in git.notes_list()


def test_prune_reports_when_there_is_nothing_to_do(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "skip")
    run("note", "prune")
    assert capsys.readouterr().out.strip() == ""


# --- 備註掛在本地沒有的物件上 ---

ABSENT_OBJECT = "0123456789abcdef0123456789abcdef01234567"


def test_backup_survives_a_note_on_an_object_that_is_not_here(
    git_repo, commit, no_remote, notes_tree, capsys
):
    """backup 是 prune 的安全網，一筆讀不到就整份倒不出來是不能接受的。"""
    head = commit("feat: 還在的")
    notes_tree({head: "type: feat\nchange_log: 有內容\n", ABSENT_OBJECT: "type: fix\nchange_log: 也有內容\n"})
    assert cli.main(["--no-push", "note", "backup"]) == 0
    dumped = capsys.readouterr().out
    assert "有內容" in dumped
    assert "也有內容" in dumped


def test_backup_marks_the_ones_whose_commit_is_missing(
    git_repo, commit, no_remote, notes_tree, capsys
):
    head = commit("feat: 還在的")
    notes_tree({head: "type: feat\nchange_log: 有內容\n", ABSENT_OBJECT: "type: fix\nchange_log: 也有內容\n"})
    cli.main(["--no-push", "note", "backup"])
    assert ABSENT_OBJECT in capsys.readouterr().out


def test_prune_survives_a_blank_note_on_an_object_that_is_not_here(
    git_repo, commit, no_remote, notes_tree, capsys
):
    head = commit("feat: 還在的")
    notes_tree({head: "type: feat\n", ABSENT_OBJECT: "type: ''\nchange_log: ''\n"})
    assert cli.main(["--no-push", "note", "prune"]) == 0
    assert ABSENT_OBJECT in capsys.readouterr().out


def test_list_is_unaffected_by_notes_on_missing_objects(
    git_repo, commit, no_remote, notes_tree, capsys
):
    base = commit("feat: base")
    head = commit("feat: 還在的")
    notes_tree({ABSENT_OBJECT: "type: fix\n"})
    assert cli.main(["--no-push", "list", f"{base}...master"]) == 0
    assert head in capsys.readouterr().out


# --- AI 產生的備註與人工確認 ---


def note_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_the_ai_flag_marks_the_note_as_ai_written(git_repo, commit, no_remote, capsys):
    head = commit()
    run("note", "set", head, "--ai-generated", "--type", "fix", "--change-log", "AI 寫的")
    run("note", "show", "--format", "json")
    written = note_json(capsys)
    assert written["ai_generated"] is True
    assert written["change_log"] == "AI 寫的"


def test_a_note_written_without_the_flag_carries_no_marker(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "fix")
    run("note", "show", "--format", "json")
    assert "ai_generated" not in note_json(capsys)


def test_a_human_write_afterwards_clears_the_marker(git_repo, commit, no_remote, capsys):
    """審閱過的備註與人工填的備註沒有兩樣——不必另外下指令清記號。"""
    head = commit()
    run("note", "set", head, "--ai-generated", "--type", "fix")
    run("note", "set", head, "--change-log", "人改的")
    run("note", "show", "--format", "json")
    assert note_json(capsys) == {"type": "fix", "change_log": "人改的"}


def test_the_ai_cannot_fill_a_human_only_field(git_repo, commit, no_remote, capsys):
    commit()
    assert cli.main(["--no-push", "note", "set", "--ai-generated", "--type", "fix", "--spec-change", "規格動了"]) != 0
    assert "人工" in capsys.readouterr().err


def test_a_human_may_still_fill_a_human_only_field(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--type", "fix", "--spec-change", "規格動了")
    run("note", "show", "--format", "json")
    assert note_json(capsys)["spec_change"] == "規格動了"


def test_the_ai_may_not_smuggle_a_human_only_field_through_stdin(
    git_repo, commit, no_remote, monkeypatch, capsys
):
    commit()
    monkeypatch.setattr("sys.stdin", _Stdin('{"type": "fix", "data_migration": "搬"}'))
    assert cli.main(["--no-push", "note", "set", "--from-stdin", "--format", "json", "--ai-generated"]) != 0
    assert "人工" in capsys.readouterr().err


def test_list_can_filter_down_to_the_waiting_ones(git_repo, commit, no_remote, capsys):
    base = commit("feat: base")
    ai_written = commit("fix: AI 填的")
    human_written = commit("fix: 人填的")
    run("note", "set", ai_written, "--ai-generated", "--type", "fix")
    run("note", "set", human_written, "--type", "fix")
    run("list", f"{base}...master", "--filter", "ai-generated", "--format", "json")
    payload = json.loads(capsys.readouterr().out)
    assert [entry["commit"] for entry in payload] == [ai_written]


def test_the_editor_can_be_pointed_at_the_waiting_ones(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--ai-generated"])
    assert spy_editor["ai_only"] is True


def test_the_editor_defaults_to_everything_but_the_waiting_filter(
    git_repo, commit, no_remote, spy_editor
):
    commit()
    cli.main([])
    assert spy_editor["ai_only"] is False


def test_push_reports_cleanly_when_there_is_no_origin(git_repo, commit, no_remote, capsys):
    """批次填寫的收尾動作。這個測試 repo 沒有 origin，所以只驗它好好報錯。"""
    commit()
    assert cli.main(["note", "push"]) != 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert captured.err.strip()


# --- 什麼時候該推送 ---


@pytest.mark.parametrize(
    ("arguments", "pushes"),
    [
        (["note", "set", "--type", "fix"], True),
        (["note", "remove"], True),
        (["note", "set", "--ai-generated", "--type", "fix"], False),
        ([], False),
    ],
)
def test_which_writes_push_by_themselves(arguments, pushes):
    options = cli.build_parser().parse_args(cli._normalise(arguments))
    assert cli._push_after_write(options) is pushes


def test_an_ai_write_does_not_even_try_to_push(git_repo, commit, no_remote):
    """這個 repo 沒有 origin：真的嘗試推送就會非零離開。"""
    commit()
    assert cli.main(["note", "set", "--ai-generated", "--type", "fix"]) == 0


def test_a_human_write_still_pushes_unless_told_not_to(git_repo, commit, unreachable_origin):
    """人工寫入會嘗試推送——推不出去就是非零，這正是「有推」的證據。"""
    commit()
    assert cli.main(["note", "set", "--type", "fix"]) != 0


def test_push_is_refused_while_something_waits_for_review(git_repo, commit, no_remote, capsys):
    commit()
    run("note", "set", "--ai-generated", "--type", "fix")
    assert cli.main(["note", "push"]) != 0
    assert "待確認" in capsys.readouterr().err




def test_the_sync_notice_reaches_stderr_without_failing_the_command(
    git_repo, commit, origin, monkeypatch, capsys
):
    """兩邊分歧是說明，不是錯誤：指令照做完，結束碼是 0。"""
    monkeypatch.setattr(cli, "DEFAULT_FETCH", True)
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    shared = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)
    second = commit()
    git.notes_add(second, "type: fix", force=False)
    git.notes_push("origin")
    run_git("update-ref", git.NOTES_REF, shared, cwd=git_repo)
    git.notes_add(second, "type: feat", force=True)

    assert cli.main(["--no-push", "list", f"{head}...master"]) == 0
    assert "分歧" in capsys.readouterr().err


# --- init：宣告檔從範本長出來 ---


def test_init_writes_what_the_questions_produced(git_repo, no_remote, monkeypatch):
    """init 寫下的是問出來的欄位，不是一份現成的。"""
    monkeypatch.delenv("GNE_SCHEMA", raising=False)

    answered = {
        **schema.blank_declaration(),
        "properties": {
            "note": {"title": "備註", "type": "string", "x-prompt": "隨便寫。", "x-input": "text"}
        },
    }
    monkeypatch.setattr(cli, "interactive_possible", lambda: True)
    monkeypatch.setattr(cli, "run_field_setup", lambda: FieldPlan(document=answered))

    run("schema", "init")

    declaration = git_repo / ".gne" / "note-schema.json"
    assert list(json.loads(declaration.read_text(encoding="utf-8"))["properties"]) == ["note"]


def test_init_needs_a_terminal_because_it_asks(git_repo, no_remote, monkeypatch, capsys):
    monkeypatch.delenv("GNE_SCHEMA", raising=False)
    monkeypatch.setattr(cli, "interactive_possible", lambda: False)
    assert cli.main(["schema", "init"]) != 0
    assert "需要終端機" in capsys.readouterr().err


def test_init_leaves_nothing_behind_when_the_questions_are_abandoned(
    git_repo, no_remote, monkeypatch
):
    monkeypatch.delenv("GNE_SCHEMA", raising=False)
    monkeypatch.setattr(cli, "interactive_possible", lambda: True)
    monkeypatch.setattr(cli, "run_field_setup", lambda: None)

    assert cli.main(["schema", "init"]) != 0
    assert not (git_repo / ".gne" / "note-schema.json").exists()


MINIMAL_DECLARATION = json.dumps(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {"note": {"title": "備註", "type": "string", "x-prompt": "隨便寫。"}},
    },
    ensure_ascii=False,
)


def test_init_does_not_overwrite_an_existing_declaration(git_repo, no_remote, monkeypatch):
    monkeypatch.delenv("GNE_SCHEMA", raising=False)
    declaration = git_repo / ".gne" / "note-schema.json"
    declaration.parent.mkdir()
    declaration.write_text(MINIMAL_DECLARATION, encoding="utf-8")
    run("schema", "init")
    assert declaration.read_text(encoding="utf-8") == MINIMAL_DECLARATION


def test_a_declaration_that_is_not_json_says_which_file(git_repo, no_remote, monkeypatch, capsys):
    """自己手改宣告檔改壞了，要看得懂是哪一個檔壞了，而不是一份 traceback。"""
    monkeypatch.delenv("GNE_SCHEMA", raising=False)
    declaration = git_repo / ".gne" / "note-schema.json"
    declaration.parent.mkdir()
    declaration.write_text("{ 這不是 JSON", encoding="utf-8")
    run("schema", "show", expect=1)
    assert "note-schema.json" in capsys.readouterr().err


def test_a_repo_without_a_declaration_is_told_what_to_run(git_repo, commit, no_remote, monkeypatch, capsys):
    commit()
    monkeypatch.delenv("GNE_SCHEMA", raising=False)
    run("schema", "show", expect=1)
    assert "gne init" in capsys.readouterr().err


# --- 區間：給過一次就不必再講 ---


def test_a_range_given_once_is_reused(git_repo, commit, no_remote, capsys):
    base = commit("feat: base")
    commit("feat: later")
    run("list", f"{base}...master")
    first = capsys.readouterr().out
    run("list")
    assert capsys.readouterr().out == first


def test_without_a_range_and_without_a_memory_it_says_so(git_repo, commit, no_remote, capsys):
    commit()
    run("list", expect=1)
    assert "沒有指定區間" in capsys.readouterr().err


# --- order：欄位的顯示順序 ---


def test_order_prints_the_current_order(git_repo, commit, no_remote, capsys):
    commit()
    run("schema", "order")
    assert capsys.readouterr().out.split() == [field.key for field in schema.note_fields()]


def test_order_rearranges_the_declaration(git_repo, commit, no_remote, monkeypatch, tmp_path):
    """順序就是顯示順序，所以重排是改宣告檔，不是改畫面。"""
    commit()
    declaration = tmp_path / "note-schema.json"
    declaration.write_text(schema.EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(schema.SCHEMA_ENV, str(declaration))
    schema.forget_schema()

    run("schema", "order", "redmine_ids", "type", "change_log", "spec_change", "data_migration")

    assert list(json.loads(declaration.read_text(encoding="utf-8"))["properties"]) == [
        "redmine_ids",
        "type",
        "change_log",
        "spec_change",
        "data_migration",
    ]


def test_order_refuses_a_partial_list(git_repo, commit, no_remote, capsys):
    """漏掉的欄位不是「排在後面」，是會消失——所以要列齊。"""
    commit()
    assert cli.main(["schema", "order", "type"]) != 0
    assert "剛好一次" in capsys.readouterr().err


# --- 指令表面：五個入口，不多不少 ---


def test_the_advertised_commands_are_the_five_entry_points():
    """編輯器沒有對外的名字（gne <區間> 就是它），其餘四個各管一件事。

    這一條擋的是指令表面長回去：多一個對外的名字就要有人解釋它跟誰不重複。
    """
    listing = cli.build_parser()._subparsers._group_actions[0]
    advertised = {action.dest for action in listing._choices_actions}
    assert advertised == {"export", "list", "note", "schema"}


def test_everything_a_person_does_in_the_editor_has_a_command():
    """編輯器裡改得動的東西，不進畫面也要做得到——那條路是給腳本與 AI 走的。"""
    listing = cli.build_parser()._subparsers._group_actions[0]
    notes = listing.choices["note"]._subparsers._group_actions[0].choices
    assert set(notes) == {"show", "set", "remove", "prune", "backup", "push"}


def test_the_schema_commands_cover_declaring_and_ordering():
    listing = cli.build_parser()._subparsers._group_actions[0]
    declaration = listing.choices["schema"]._subparsers._group_actions[0].choices
    assert set(declaration) == {"show", "init", "order"}


# --- 唯讀 ---


def test_read_only_reaches_the_editor(git_repo, commit, no_remote, spy_editor):
    commit()
    cli.main(["--read-only"])
    assert spy_editor["read_only"] is True


def test_read_only_does_not_push(git_repo, commit, no_remote, spy_editor):
    """唯讀不寫東西，也就沒有東西要推。"""
    commit()
    cli.main(["--read-only"])
    assert spy_editor["push"] is False
