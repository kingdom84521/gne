"""gne 的命令列介面。

每個子命令都能在沒有終端機的情況下完成，互動式編輯器只是其中一種入口。
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import export, render
from .core import git, provenance, schema
from .core.entity import ERROR_ID, NoteController, NoteError, NoteSyncError

DEFAULT_FETCH = True

SUBCOMMANDS = (
    "init",
    "order",
    "edit",
    "show",
    "list",
    "export",
    "schema",
    "set",
    "remove",
    "prune",
    "backup",
    "push",
)

MISSING_COMMIT = "（這個 commit 不在本地 repository）"

# 只有這些旗標能排在子命令前面。子命令自己的旗標必須排在子命令後面，
# 所以補上 edit 的位置由它決定。與實際的 parser 一致由 test_cli.py 釘住。
GLOBAL_FLAGS = frozenset({"-h", "--help", "--no-push"})

HEADLESS_ADVICE = (
    "互動式編輯器需要終端機，目前沒有。\n"
    "改用不進 TUI 的子命令：gne show / gne list / gne set / gne remove。\n"
    "欄位與可用旗標請看 gne schema。"
)


def _declared_fields() -> tuple[schema.NoteField, ...]:
    """gne set 的旗標由宣告檔衍生，但組 parser 不能要求宣告檔已經存在。

    還沒 gne init 的 repo、根本不在 repo 裡的 cwd——這兩種情況下 gne --help 與
    gne init 都還是要能用。真的需要欄位的子命令會在執行時拿到該有的錯誤訊息。
    """
    try:
        return schema.note_fields()
    except (schema.SchemaNotDeclared, schema.SchemaDeclarationError, git.GitError):
        return ()


def interactive_possible() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_editor(controller: NoteController, **arguments: object) -> None:
    """延後匯入，讓沒有終端機的路徑不必載入 TUI。"""
    from .tui import run_editor as start

    start(controller, **arguments)


def _normalise(argv: Sequence[str]) -> list[str]:
    """讓 `gne`、`gne <hash>` 與 `gne --all-authors` 這幾種舊用法都導向編輯器。

    插入點是第一個不是全域旗標的引數：編輯器自己的旗標得排在 edit 之後，
    否則會被頂層 parser 當成不認得的引數擋下來。
    """
    result = list(argv)
    index = 0
    while index < len(result) and result[index] in GLOBAL_FLAGS:
        index += 1
    if index == len(result) or result[index] not in SUBCOMMANDS:
        result.insert(index, "edit")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gne", description="git note 編輯與匯出")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="異動後不推送 refs/notes 到 origin（批次填寫時建議開啟）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    editor = subparsers.add_parser("edit", help="開啟互動式編輯器")
    editor.add_argument("commit", nargs="?", default=None, help="只編輯這一筆，省略則列出待填的 commit")
    editor.add_argument("--range", default=None, help="要列出的 commit 區間，預設同 gne list")
    editor.add_argument("--author", default=None, help="只列出這個 email 的 commit，預設是自己")
    editor.add_argument("--all-authors", action="store_true", help="列出所有人的 commit")
    editor.add_argument("--include-noted", action="store_true", help="連已經有備註的 commit 也列出來")
    editor.add_argument(
        "--ai-generated",
        action="store_true",
        help="只列出 AI 產生、還沒有人工確認的那些（儲存這一筆就等於確認）",
    )

    shower = subparsers.add_parser("show", help="印出單一 commit 的備註")
    shower.add_argument("commit", nargs="?", default="HEAD")
    shower.add_argument("--format", choices=("text", "yaml", "json"), default="text")

    lister = subparsers.add_parser("list", help="列出區間內的 commit 與其備註")
    lister.add_argument("range", nargs="?", default=None)
    lister.add_argument(
        "--filter", choices=("all", "noted", "unnoted", "ai-generated"), default="all"
    )
    lister.add_argument("--format", choices=("text", "json"), default="text")

    exporter = subparsers.add_parser("export", help="把區間匯出成 xlsx")
    exporter.add_argument("range", nargs="?", default=None)
    exporter.add_argument("-o", "--output", default=None)

    subparsers.add_parser("init", help="問幾題，建立這個 repo 的欄位宣告")

    orderer = subparsers.add_parser("order", help="欄位的顯示順序")
    orderer.add_argument(
        "keys",
        nargs="*",
        metavar="KEY",
        help="照這個順序重排。不給就印出現在的順序。",
    )

    describer = subparsers.add_parser("schema", help="印出欄位宣告")
    describer.add_argument("--format", choices=("text", "json"), default="text")

    setter = subparsers.add_parser("set", help="不進 TUI 直接寫入備註")
    setter.add_argument("commit", nargs="?", default="HEAD")
    setter.add_argument("--from-stdin", action="store_true", help="從 stdin 讀入整份備註並覆寫")
    setter.add_argument("--format", choices=("yaml", "json"), default="yaml")
    setter.add_argument(
        "--ai-generated",
        action="store_true",
        help="標記這次寫入是 AI 產生的，待人工確認（gne --ai-generated 會列出來）",
    )
    for field in _declared_fields():
        setter.add_argument(
            field.cli_flag,
            dest=f"field_{field.key}",
            default=None,
            metavar=field.key.upper(),
            help=f"{field.title}（{field.input}）",
        )

    remover = subparsers.add_parser("remove", help="刪除某個 commit 的備註")
    remover.add_argument("commit", nargs="?", default="HEAD")

    pruner = subparsers.add_parser("prune", help="移除每個欄位都空的備註")
    pruner.add_argument("--apply", action="store_true", help="真的移除，預設只列出")
    pruner.add_argument("--yes", action="store_true", help="確認已備份，允許 --apply 動手")

    backer = subparsers.add_parser("backup", help="傾印所有帶內容的備註")
    backer.add_argument("-o", "--output", default=None)

    subparsers.add_parser("push", help="把本機的 refs/notes 推到 origin")

    return parser


def collect_rows(
    controller: NoteController, revision_range: str, note_filter: str
) -> list[dict[str, Any]]:
    notes = controller.all_notes()
    rows: list[dict[str, Any]] = []
    for revision in git.commits_in_range(revision_range):
        note = notes.get(revision)
        if note_filter == "noted" and note is None:
            continue
        if note_filter == "unnoted" and note is not None:
            continue
        if note_filter == "ai-generated" and not (note and provenance.is_ai_generated(note)):
            continue
        rows.append(
            {
                "commit": revision,
                "subject": git.commit_subject(revision),
                "author": git.commit_author(revision),
                "date": git.commit_date(revision),
                "note": note,
            }
        )
    return rows


def _emit(text: str, target: str | None) -> None:
    if target is None:
        print(text)
        return
    Path(target).write_text(text + "\n", encoding="utf-8")
    print(f"已寫入 {target}", file=sys.stderr)


def _edit_author(options: argparse.Namespace) -> str | None:
    if options.all_authors:
        return None
    return options.author or git.current_user_email()


def _run_edit(controller: NoteController, options: argparse.Namespace) -> int:
    if not interactive_possible():
        print(HEADLESS_ADVICE, file=sys.stderr)
        return 1

    if options.commit is not None:
        if not git.commit_exists(options.commit):
            raise NoteError(ERROR_ID.COMMIT_NOT_FOUND, options.commit)
        run_editor(controller, only=git.resolve_commit(options.commit), push=not options.no_push)
        return 0

    run_editor(
        controller,
        revision_range=options.range,
        author_email=_edit_author(options),
        unnoted_only=not options.include_noted,
        ai_only=options.ai_generated,
        push=not options.no_push,
    )
    return 0


def _run_show(controller: NoteController, options: argparse.Namespace) -> int:
    document = controller.read_raw(options.commit)
    renderer = {
        "text": render.note_as_text,
        "yaml": render.note_as_yaml,
        "json": render.note_as_json,
    }[options.format]
    print(renderer(document))
    return 0


def _run_list(controller: NoteController, options: argparse.Namespace) -> int:
    revision_range = git.resolve_range(options.range)
    rows = collect_rows(controller, revision_range, options.filter)
    if options.format == "json":
        print(render.rows_as_json(rows))
    else:
        rendered = render.rows_as_text(rows)
        if rendered:
            print(rendered)
    print(f"{len(rows)} 筆", file=sys.stderr)
    return 0


def _run_export(controller: NoteController, options: argparse.Namespace) -> int:
    revision_range = git.resolve_range(options.range)
    rows = collect_rows(controller, revision_range, "all")
    target = Path(options.output or f"{git.current_branch()}.xlsx")
    export.write_workbook(export.build_workbook(rows), target)
    print(f"已匯出 {target}", file=sys.stderr)
    return 0


def run_field_setup() -> object:
    """延後匯入，讓沒有終端機的路徑不必載入 TUI。"""
    from .tui import run_field_setup as ask

    return ask()


def _run_init(_: NoteController, __: argparse.Namespace) -> int:
    """問出這個專案的欄位。

    不複製一份現成的欄位進來：release note 要記什麼是各專案自己的事，塞一份別人的
    欄位給你，最可能的結果是它就一直留在那裡。
    """
    target = schema.schema_path()
    if target.exists():
        print(f"{target} 已經在了，沒有動它。", file=sys.stderr)
        return 0

    if not interactive_possible():
        raise render.InputError(
            "gne init 會問你這個專案要記哪些欄位，需要終端機。\n"
            f"要用現成的宣告就直接把檔案放到 {target}，或用 GNE_SCHEMA 指過去。"
        )

    plan = run_field_setup()
    if plan is None:
        print("沒有建立宣告檔。", file=sys.stderr)
        return 1

    written = schema.save_schema(plan.document)
    print(f"已建立 {written}。之後改欄位用 gne edit 裡的 ctrl+f。", file=sys.stderr)
    return 0


def _run_order(_: NoteController, options: argparse.Namespace) -> int:
    document = schema.load_schema()
    if not options.keys:
        print("\n".join(document["properties"]))
        return 0

    schema.save_schema(schema.reordered(document, options.keys))
    print("已重排欄位順序。", file=sys.stderr)
    return 0


def _run_schema(_: NoteController, options: argparse.Namespace) -> int:
    if options.format == "json":
        print(json.dumps(schema.load_schema(), ensure_ascii=False, indent=2))
    else:
        print(render.schema_as_text())
    return 0


def _run_set(controller: NoteController, options: argparse.Namespace) -> int:
    given = {
        field.key: getattr(options, f"field_{field.key}")
        for field in schema.note_fields()
        if getattr(options, f"field_{field.key}") is not None
    }

    if options.from_stdin and given:
        raise render.InputError("--from-stdin 會覆寫整份備註，不能同時指定個別欄位旗標。")
    if not options.from_stdin and not given:
        raise render.InputError(
            "沒有指定任何欄位。用個別旗標（見 gne schema）或 --from-stdin 提供內容。"
        )

    if options.from_stdin:
        document = render.parse_note(sys.stdin.read(), options.format)
        written = tuple(provenance.fields_of(document))
    else:
        document = dict(controller.read_raw(options.commit)) if controller.is_exist(options.commit) else {}
        for key, raw in given.items():
            document[key] = schema.parse_value(schema.field_by_key()[key], raw)
        written = tuple(given)

    controller.add(_attributed(document, written, options.ai_generated), options.commit, isForce=True)
    return 0


def _attributed(
    document: dict[str, Any], written: Sequence[str], by_ai: bool
) -> dict[str, Any]:
    """人工寫入就是人工寫入：沒有 --ai-generated，先前的 AI 記號在這次寫入後消失。"""
    if by_ai:
        return provenance.stamped(document, written)
    return provenance.cleared(document)


def _push_after_write(options: argparse.Namespace) -> bool:
    """這次的寫入要不要順手推送。

    edit 的推送時機由編輯器自己掌握：批次寫入完推一次，逐筆自動推送會讓一次儲存
    推 N 次。AI 產生的備註則是根本推不上去（未確認的記號擋在 pre-push），試一次
    註定失敗的推送只會多一則錯誤訊息。
    """
    if options.no_push or options.command == "edit":
        return False
    return not (options.command == "set" and options.ai_generated)


def _run_push(controller: NoteController, _: argparse.Namespace) -> int:
    controller.push()
    print("已把 refs/notes 推到 origin", file=sys.stderr)
    return 0


def _run_remove(controller: NoteController, options: argparse.Namespace) -> int:
    controller.remove(options.commit)
    return 0


def _blank_notes(controller: NoteController) -> dict[str, dict[str, Any]]:
    return {
        revision: document
        for revision, document in controller.all_notes().items()
        if schema.is_blank_note(document)
    }


def _run_prune(controller: NoteController, options: argparse.Namespace) -> int:
    blanks = _blank_notes(controller)

    if options.apply and not options.yes:
        print(
            "prune --apply 會刪除備註。確認已經跑過 gne backup 並留下 refs/notes 備份後，"
            "再加上 --yes 執行。",
            file=sys.stderr,
        )
        return 1

    if not blanks:
        print("沒有全空的備註。", file=sys.stderr)
        return 0

    subjects = git.commit_subjects(blanks)
    for revision in sorted(blanks):
        print(f"{revision}  {subjects.get(revision, MISSING_COMMIT)}")

    if not options.apply:
        print(f"{len(blanks)} 筆全空備註（尚未移除，加上 --apply --yes 才會動手）", file=sys.stderr)
        return 0

    for revision in blanks:
        controller.remove(revision)
    print(f"已移除 {len(blanks)} 筆全空備註", file=sys.stderr)
    return 0


def _run_backup(controller: NoteController, options: argparse.Namespace) -> int:
    notes = controller.all_notes()
    subjects = git.commit_subjects(notes)
    blocks: list[str] = []
    for revision, document in sorted(notes.items()):
        if schema.is_blank_note(document):
            continue
        body = render.note_as_yaml(document)
        indented = "\n".join(f"{render.INDENT}{line}" for line in body.splitlines())
        blocks.append(f"=== {revision}  {subjects.get(revision, MISSING_COMMIT)}\n{indented}")
    _emit("\n".join(blocks), options.output)
    return 0


_HANDLERS = {
    "init": _run_init,
    "order": _run_order,
    "edit": _run_edit,
    "show": _run_show,
    "list": _run_list,
    "export": _run_export,
    "schema": _run_schema,
    "set": _run_set,
    "remove": _run_remove,
    "prune": _run_prune,
    "backup": _run_backup,
    "push": _run_push,
}


def _report_sync(controller: NoteController, code: int) -> int:
    """同步狀態是說明，不是錯誤：印出來但不影響結束碼。

    取走而不是讀取：編輯器已經在畫面裡說過的話，不該在它結束之後又留一行在終端機上。
    """
    notice = controller.take_sync_notice()
    if notice:
        print(notice, file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _normalise(sys.argv[1:] if argv is None else argv)
    try:
        options = build_parser().parse_args(arguments)
    except SystemExit as exit_request:
        return int(exit_request.code or 0)

    controller = NoteController(
        {"schematic": "yaml", "fetch": DEFAULT_FETCH, "push": _push_after_write(options)}
    )

    try:
        return _report_sync(controller, _HANDLERS[options.command](controller, options))
    except (
        NoteError,
        NoteSyncError,
        git.GitError,
        git.RangeNotGiven,
        git.RemoteUnclear,
        schema.SchemaNotDeclared,
        render.InputError,
        export.ExportError,
        schema.NoteValidationError,
        schema.SchemaDeclarationError,
        schema.FieldInputError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
