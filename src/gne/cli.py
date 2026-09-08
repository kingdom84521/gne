"""gne 的命令列介面。

每個子命令都能在沒有終端機的情況下完成，互動式編輯器只是其中一種入口。
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import export, render
from .core import fields, git, provenance, revisions, schema
from .core.entity import ERROR_ID, NoteController, NoteError, NoteSyncError
from .core.fields import INPUT_KINDS, FieldDraft, FieldPlan, draft_of, read_pairs

DEFAULT_FETCH = True

EDITOR_USAGE = """開編輯器（沒有子命令名字，這就是 gne 平常在做的事）：

  gne                       區間由 GNE_FROM / GNE_TO 或上一次用過的決定
  gne <區間>                例如 gne v1.2.0...HEAD
  gne <hash>                只編輯這一筆

  --from-file / --to-file   從檔案讀區間的兩端
  --read-only               唯讀：看得到全部，改不了任何東西
  --all-authors             列出所有人的 commit，預設只有自己的
  --author <email>          只列這個人的
  --include-noted           連已經有備註的也列出來
  --ai-generated            只列 AI 填了、還沒有人工確認的那些
"""

EDITOR_COMMAND = "edit"
"""編輯器 parser 的內部名字。使用者打的是 `gne <區間>`，不是這個。"""

SUBCOMMANDS = ("export", "list", "note", "schema")

MISSING_COMMIT = "（這個 commit 不在本地 repository）"

# 只有這些旗標能排在子命令前面。子命令自己的旗標必須排在子命令後面，
# 所以補上 edit 的位置由它決定。與實際的 parser 一致由 test_cli.py 釘住。
GLOBAL_FLAGS = frozenset({"-h", "--help", "--no-push"})

HEADLESS_ADVICE = (
    "互動式編輯器需要終端機，目前沒有。\n"
    "不進畫面也做得到：gne list 看有哪些、gne note show 看一筆、gne note set 寫一筆。\n"
    "欄位與可用旗標請看 gne schema show。"
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
    """`gne`、`gne <區間>`、`gne <hash>`、`gne --all-authors` 都是開編輯器。

    編輯器沒有對外的名字，所以第一個不是全域旗標的引數若不是某個子命令，就是要開
    編輯器——在那個位置補上內部名字。補在那個位置而不是最前面：編輯器自己的旗標得
    排在它後面，否則會被頂層 parser 當成不認得的引數擋下來。
    """
    result = list(argv)
    index = 0
    while index < len(result) and result[index] in GLOBAL_FLAGS:
        index += 1
    if index == len(result) or result[index] not in SUBCOMMANDS:
        result.insert(index, EDITOR_COMMAND)
    return result


def build_parser() -> argparse.ArgumentParser:
    """五個入口：編輯器、export、list、note、schema。

    編輯器沒有自己的名字——`gne <區間>` 就是它，因為那是這個工具平常在做的事。
    其餘四個各管一件事：輸出文件、用文字看、逐條改備註、改欄位宣告。人在編輯器裡
    做得到的每一件事，`gne note` 底下都有一條指令做得到，那條路是給腳本與 AI 走的。
    """
    parser = argparse.ArgumentParser(
        prog="gne",
        description="git note 編輯與匯出",
        epilog=EDITOR_USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="異動後不推送 refs/notes（批次填寫時建議開啟）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    ranged = _range_sources()
    _add_editor(subparsers, ranged)

    exporter = subparsers.add_parser(
        "export", help="把區間匯出成 xlsx，不管填到什麼程度", parents=[ranged]
    )
    exporter.add_argument("range", nargs="?", default=None)
    exporter.add_argument("-o", "--output", default=None)

    lister = subparsers.add_parser(
        "list", help="用文字列出區間內的 commit 與備註", parents=[ranged]
    )
    lister.add_argument("range", nargs="?", default=None)
    lister.add_argument(
        "--filter",
        choices=("all", "noted", "unnoted", "ai-generated"),
        default="all",
        help="all 全部｜noted 已經有備註的｜unnoted 還沒填的｜ai-generated AI 填了待確認的",
    )
    lister.add_argument("--format", choices=("text", "json"), default="text")

    _add_note_commands(subparsers)
    _add_schema_commands(subparsers)

    return parser


def _range_sources() -> argparse.ArgumentParser:
    """區間兩端可以從哪裡來。吃區間的入口共用這一組。"""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--from-file", default=None, metavar="PATH", help="從這個檔案讀區間的起點"
    )
    shared.add_argument(
        "--to-file", default=None, metavar="PATH", help="從這個檔案讀區間的終點"
    )
    shared.add_argument(
        "--yes",
        action="store_true",
        help="有設定被更高位階的值蓋掉時不要問，照著做",
    )
    return shared


def _add_editor(subparsers: argparse._SubParsersAction, ranged: argparse.ArgumentParser) -> None:
    """編輯器的旗標。這個 parser 沒有對外的名字，由 _normalise 導過來。"""
    # 不給 help：argparse 只把有 help 的子命令列進說明，所以這一個 parse 得動、
    # 但不會出現在 gne --help 的清單上。使用者看到的入口就是 `gne <區間>`。
    editor = subparsers.add_parser(EDITOR_COMMAND, parents=[ranged])
    editor.add_argument(
        "target",
        nargs="?",
        default=None,
        help="要看的區間（a...b），或單獨一個 hash 只編輯那一筆",
    )
    editor.add_argument("--author", default=None, help="只列出這個 email 的 commit，預設是自己")
    editor.add_argument("--all-authors", action="store_true", help="列出所有人的 commit")
    editor.add_argument("--include-noted", action="store_true", help="連已經有備註的也列出來")
    editor.add_argument(
        "--ai-generated",
        action="store_true",
        help="只列出 AI 產生、還沒有人工確認的那些（儲存這一筆就等於確認）",
    )
    editor.add_argument(
        "--read-only",
        action="store_true",
        help="唯讀：看得到全部，但改不了任何東西，也不會推送",
    )


def _add_note_commands(subparsers: argparse._SubParsersAction) -> None:
    """人在編輯器裡做的事，一條指令一件。這條路不進畫面，給腳本與 AI 用。"""
    notes = subparsers.add_parser("note", help="逐條讀寫備註（不進畫面）")
    actions = notes.add_subparsers(dest="note_command", required=True, metavar="<action>")

    shower = actions.add_parser("show", help="印出單一 commit 的備註")
    shower.add_argument("commit", nargs="?", default="HEAD")
    shower.add_argument("--format", choices=("text", "yaml", "json"), default="text")

    setter = actions.add_parser("set", help="寫入備註，未給的欄位保留原值")
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

    remover = actions.add_parser("remove", help="刪除某個 commit 的備註")
    remover.add_argument("commit", nargs="?", default="HEAD")

    pruner = actions.add_parser("prune", help="移除每個欄位都空的備註")
    pruner.add_argument("--apply", action="store_true", help="真的移除，預設只列出")
    pruner.add_argument("--yes", action="store_true", help="確認已備份，允許 --apply 動手")

    backer = actions.add_parser("backup", help="傾印所有帶內容的備註")
    backer.add_argument("-o", "--output", default=None)

    actions.add_parser("push", help="把本機的 refs/notes 推上去")


def _add_schema_commands(subparsers: argparse._SubParsersAction) -> None:
    """欄位宣告的一切都在這底下：有哪些欄位、怎麼問、什麼順序。"""
    declaration = subparsers.add_parser("schema", help="欄位宣告")
    actions = declaration.add_subparsers(dest="schema_command", required=True, metavar="<action>")

    shower = actions.add_parser("show", help="印出欄位宣告")
    shower.add_argument("--format", choices=("text", "json"), default="text")

    actions.add_parser("init", help="問出這個 repo 要記哪些欄位")

    orderer = actions.add_parser("order", help="欄位的顯示順序")
    orderer.add_argument(
        "keys",
        nargs="*",
        metavar="KEY",
        help="照這個順序重排。不給就印出現在的順序。",
    )

    adder = actions.add_parser("add", help="加一個欄位")
    adder.add_argument("key", help="備註裡的鍵，例如 change_log")
    _add_field_flags(adder, required_prompt=True)

    editor = actions.add_parser("edit", help="改一個欄位，沒給的旗標保持原樣")
    editor.add_argument("key")
    editor.add_argument("--rename", default=None, metavar="NEW_KEY", help="改欄位名")
    _add_field_flags(editor, required_prompt=False)

    remover = actions.add_parser("remove", help="刪一個欄位")
    remover.add_argument("key")
    remover.add_argument("--apply", action="store_true", help="真的刪，預設只說會影響什麼")
    remover.add_argument("--yes", action="store_true", help="確認已備份，允許 --apply 動手")


def _add_field_flags(parser: argparse.ArgumentParser, *, required_prompt: bool) -> None:
    """一個欄位宣告得起來的每一件事，這裡都要有旗標。

    畫面上的表單收得下宣告檔的每一個關鍵字，命令列就不能只收一半——兩條路做得到的
    事一樣多，才輪得到人選走哪一條。成對的東西沿用表單的寫法：`feat=功能, fix=錯誤`。
    """
    parser.add_argument("--title", default=None, help="畫面上顯示的名字，預設用欄位名")
    parser.add_argument(
        "--prompt",
        default=None,
        required=required_prompt,
        help="填寫指示，人與 AI 讀的是同一份",
    )
    parser.add_argument(
        "--input", choices=INPUT_KINDS, default=None, help="輸入型別，預設 text"
    )
    parser.add_argument("--choices", default=None, metavar="值=標籤,…", help="choice 的可選值")
    parser.add_argument("--item-url", default=None, help="integer-list 每一項展開成的網址")
    parser.add_argument(
        "--ignore-when", default=None, metavar="欄位=值,…", help="什麼時候不問這一欄"
    )
    parser.add_argument(
        "--required", action=argparse.BooleanOptionalAction, default=None, help="必填"
    )
    parser.add_argument(
        "--human-only", action=argparse.BooleanOptionalAction, default=None, help="AI 填不進去"
    )
    parser.add_argument(
        "--follow-convention",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="commit 前綴對得上可選值時就用它（choice 才有）",
    )


def _confirm_shadowing(warning: str, *, assume_yes: bool) -> None:
    """低位階的設定被蓋掉時先講、再問。

    會走到這裡的通常是「我明明設了 GNE_FROM」那種情況：值本身沒錯，錯的是有人以為
    自己設定生效了。所以不安靜地照做，也不直接停手——講清楚誰蓋掉誰，讓人決定。
    """
    print(warning, file=sys.stderr)

    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise render.InputError("有設定被蓋掉了，非互動時不會替你決定：確認過就加上 --yes。")

    answer = input("要照上面選的值繼續嗎？[y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise render.InputError("停手了。")


def _range_from_sources(options: argparse.Namespace, given: str | None) -> str | None:
    """三種來源說出來的區間，都沒說話就回 None。

    兩端各自走「命令列 > 參數指定的檔案 > 環境變數」，所以 `GNE_FROM` 設好之後
    `gne` 不帶任何東西也會動。低位階的來源被蓋掉時會先問過人。

    只講得出起點時終點就是 HEAD——沒有人想為了「從某個版本到現在」多打一次 HEAD。

    上一次用過的那一個不算來源：它是這台機器的記憶，不是誰的設定，所以它被蓋掉時
    不會叫住你。三種來源都沒說話時才輪到它（見 git.resolve_range）。
    """
    ends = revisions.split_range(given) if given else None
    resolutions = [
        revisions.resolve_end(
            "起點", ends[0] if ends else None, options.from_file, revisions.FROM_ENV
        ),
        revisions.resolve_end(
            "終點", ends[1] if ends else None, options.to_file, revisions.TO_ENV
        ),
    ]

    warning = revisions.shadowing_warning(resolutions)
    if warning:
        _confirm_shadowing(warning, assume_yes=options.yes)

    start, end = (resolution.value for resolution in resolutions)
    if start:
        return revisions.compose(start, end or "HEAD")
    # 不是 a...b 的形狀（例如 `a..b`）就原樣交給 git。
    return given


def _resolved_range(options: argparse.Namespace, given: str | None) -> str:
    """不進畫面的那些指令要有區間才做得了事，所以這裡解不出來就報錯。"""
    return git.resolve_range(_range_from_sources(options, given))


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

    # 唯讀不寫東西，也就沒有東西要推。
    push = not (options.no_push or options.read_only)
    target = options.target

    # 一個 hash 是「只編這一筆」，a...b 是「看這一段」。同一個位置收兩種東西，
    # 因為使用者打的就是這兩種，不該為了分辨而多一個旗標。
    single = target if target and revisions.split_range(target) is None else None
    if single is not None:
        if not git.commit_exists(single):
            raise NoteError(ERROR_ID.COMMIT_NOT_FOUND, single)
        run_editor(
            controller,
            only=git.resolve_commit(single),
            push=push,
            read_only=options.read_only,
        )
        return 0

    run_editor(
        controller,
        # 編輯器解不出區間時是問，不是報錯——所以這裡容許 None（見 app 的 RangeScreen）。
        revision_range=_range_from_sources(options, target),
        author_email=_edit_author(options),
        unnoted_only=not options.include_noted,
        ai_only=options.ai_generated,
        push=push,
        read_only=options.read_only,
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
    revision_range = _resolved_range(options, options.range)
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
    revision_range = _resolved_range(options, options.range)
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


def _drafted(options: argparse.Namespace, base: FieldDraft | None) -> FieldDraft:
    """把命令列給的旗標套到欄位上。沒給的旗標保持原樣——edit 只改你指名的東西。"""
    starting = base or FieldDraft(key=options.key, title="", prompt="", input="text")

    def chosen(name: str, current: object) -> object:
        given = getattr(options, name, None)
        return current if given is None else given

    return FieldDraft(
        key=getattr(options, "rename", None) or options.key,
        title=chosen("title", starting.title),
        prompt=chosen("prompt", starting.prompt),
        input=chosen("input", starting.input),
        choices=(
            starting.choices
            if options.choices is None
            else read_pairs(options.choices, label_optional=True)
        ),
        item_url=chosen("item_url", starting.item_url),
        ignore_when=(
            starting.ignore_when
            if options.ignore_when is None
            else read_pairs(options.ignore_when, label_optional=False)
        ),
        required=chosen("required", starting.required),
        human_only=chosen("human_only", starting.human_only),
        follow_convention=chosen("follow_convention", starting.follow_convention),
        original_key=None if base is None else options.key,
    )


def _with_field(document: Mapping[str, Any], draft: FieldDraft) -> dict[str, Any]:
    """把一個欄位放回宣告裡，順序與必填一起維護。"""
    properties = dict(document["properties"])
    if draft.original_key and draft.original_key != draft.key:
        properties = {
            (draft.key if key == draft.original_key else key): value
            for key, value in properties.items()
        }
    properties[draft.key] = draft.as_declaration()

    required = [
        key
        for key in document.get("required", [])
        if key not in (draft.key, draft.original_key)
    ]
    if draft.required:
        required.append(draft.key)

    return {**document, "properties": properties, "required": required}


def _run_schema_add(controller: NoteController, options: argparse.Namespace) -> int:
    document = schema.load_schema()
    if options.key in document["properties"]:
        raise render.InputError(f"已經有一個欄位叫「{options.key}」了。")

    plan = FieldPlan(document=_with_field(document, _drafted(options, None)))
    fields.apply_plan(plan, controller)
    print(f"已加上欄位 {options.key}。", file=sys.stderr)
    return 0


def _run_schema_edit(controller: NoteController, options: argparse.Namespace) -> int:
    document = schema.load_schema()
    if options.key not in document["properties"]:
        raise render.InputError(f"沒有欄位叫「{options.key}」。")
    if options.rename and options.rename in document["properties"]:
        raise render.InputError(f"已經有一個欄位叫「{options.rename}」了。")

    base = draft_of(
        options.key, document["properties"][options.key], options.key in document.get("required", [])
    )
    draft = _drafted(options, base)
    renames = ((options.key, draft.key),) if draft.key != options.key else ()

    rewritten = fields.apply_plan(
        FieldPlan(document=_with_field(document, draft), renames=renames), controller
    )
    if renames:
        print(f"{options.key} 已改名為 {draft.key}，改寫了 {len(rewritten)} 筆備註。", file=sys.stderr)
    else:
        print(f"已更新欄位 {options.key}。", file=sys.stderr)
    return 0


def _run_schema_remove(controller: NoteController, options: argparse.Namespace) -> int:
    """刪欄位會把既有備註裡的那一欄一起拿掉，所以預設只說會影響什麼。"""
    document = schema.load_schema()
    if options.key not in document["properties"]:
        raise render.InputError(f"沒有欄位叫「{options.key}」。")
    if len(document["properties"]) == 1:
        raise render.InputError("一個欄位都沒有的宣告收不下。")

    carrying = controller.notes_carrying(options.key)
    if not options.apply:
        print(f"刪掉 {options.key} 會一併從 {len(carrying)} 筆備註裡拿掉它。")
        print("確定就加上 --apply --yes。", file=sys.stderr)
        return 0
    if not options.yes:
        raise render.InputError(
            f"--apply 會改寫 {len(carrying)} 筆備註，備份過了就再加上 --yes。"
        )

    properties = {
        key: value for key, value in document["properties"].items() if key != options.key
    }
    required = [key for key in document.get("required", []) if key != options.key]
    plan = FieldPlan(
        document={**document, "properties": properties, "required": required},
        drops=(options.key,),
    )
    rewritten = fields.apply_plan(plan, controller)
    print(f"已刪除欄位 {options.key}，改寫了 {len(rewritten)} 筆備註。", file=sys.stderr)
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

    編輯器的推送時機由它自己掌握：批次寫入完推一次，逐筆自動推送會讓一次儲存
    推 N 次。AI 產生的備註則是根本推不上去（未確認的記號擋在 pre-push），試一次
    註定失敗的推送只會多一則錯誤訊息。
    """
    if options.no_push or options.command == EDITOR_COMMAND:
        return False
    return not (_handler_key(options) == "note.set" and options.ai_generated)


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
    EDITOR_COMMAND: _run_edit,
    "export": _run_export,
    "list": _run_list,
    "note.show": _run_show,
    "note.set": _run_set,
    "note.remove": _run_remove,
    "note.prune": _run_prune,
    "note.backup": _run_backup,
    "note.push": _run_push,
    "schema.show": _run_schema,
    "schema.init": _run_init,
    "schema.order": _run_order,
    "schema.add": _run_schema_add,
    "schema.edit": _run_schema_edit,
    "schema.remove": _run_schema_remove,
}


def _handler_key(options: argparse.Namespace) -> str:
    """有 sub-subcommand 的分兩段查。"""
    if options.command == "note":
        return f"note.{options.note_command}"
    if options.command == "schema":
        return f"schema.{options.schema_command}"
    return options.command


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
        return _report_sync(controller, _HANDLERS[_handler_key(options)](controller, options))
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
