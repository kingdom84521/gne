"""改欄位宣告。

宣告檔是這個工具唯一的設定，以前只能手改 JSON——還得先知道 x-input、x-prompt、
x-ignore-when 是什麼。對只設定一次的專案來說那是一次性的成本，對其他人則是入口。

刪欄位與改欄位名不只是改宣告：宣告的 additionalProperties 是 false，既有備註裡
那個欄位不跟著改，下一次讀取就整批驗證失敗。所以這個畫面產出的不是一份新宣告，
而是一份計畫——新宣告加上「既有備註要跟著做什麼」，由呼叫端一起執行。
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Switch
from textual.widgets.option_list import Option

from ...core import schema
from .confirm import ConfirmScreen
from .dialog import BOX_CLASS, CLOSE_HINT, Dialog

INPUT_KINDS = ("text", "multiline", "integer-list", "choice")

LIST_ID = "fields-list"
ERROR_ID = "fields-error"

HINT = f"a 新增 ｜ e 修改 ｜ d 刪除 ｜ ctrl+s 儲存；{CLOSE_HINT}"
FORM_HINT = f"ctrl+s 收下這一欄；{CLOSE_HINT}"


@dataclass(frozen=True)
class FieldPlan:
    """改完的宣告，以及既有備註要跟著做的事。"""

    document: dict[str, Any]
    renames: tuple[tuple[str, str], ...] = ()
    drops: tuple[str, ...] = ()

    @property
    def touches_existing_notes(self) -> bool:
        return bool(self.renames or self.drops)


@dataclass
class FieldDraft:
    """表單收到的一個欄位。

    可選值與「什麼時候不問」都是成對的東西（值對標籤、欄位對值），表單裡各佔一格，
    寫成 `feat=功能, fix=錯誤`——一個 choice 欄位有幾個可選值不固定，做成幾格輸入
    就得在打字中途重畫表單。
    """

    key: str
    title: str
    prompt: str
    input: str
    choices: tuple[tuple[str, str], ...] = ()
    """(可選值, 顯示名稱)。"""
    item_url: str = ""
    ignore_when: tuple[tuple[str, str], ...] = ()
    """(別的欄位, 那個欄位的值)。成立時這一欄就不問。"""
    required: bool = False
    human_only: bool = False
    follow_convention: bool = False
    original_key: str | None = None

    def as_declaration(self) -> dict[str, Any]:
        declaration: dict[str, Any] = {
            "title": self.title or self.key,
            "x-prompt": self.prompt,
            "x-input": self.input,
        }
        if self.input == "integer-list":
            declaration["type"] = "array"
            declaration["items"] = {"type": "integer"}
        else:
            declaration["type"] = "string"
        if self.choices:
            declaration["enum"] = [value for value, _ in self.choices]
            declaration["x-choice-labels"] = {value: label for value, label in self.choices}
        if self.item_url:
            declaration["x-item-url"] = self.item_url
        if self.ignore_when:
            declaration["x-ignore-when"] = dict(self.ignore_when)
        if self.human_only:
            declaration["x-human-only"] = True
        if self.follow_convention:
            declaration["x-follow-convention"] = True
        return declaration


def draft_of(key: str, declaration: Mapping[str, Any], required: bool) -> FieldDraft:
    labels = declaration.get("x-choice-labels", {})
    return FieldDraft(
        key=key,
        title=declaration.get("title", key),
        prompt=declaration.get("x-prompt", ""),
        input=declaration.get("x-input", "text"),
        choices=tuple(
            (value, labels.get(value, value)) for value in declaration.get("enum", ())
        ),
        item_url=declaration.get("x-item-url", ""),
        ignore_when=tuple(
            (name, str(value)) for name, value in declaration.get("x-ignore-when", {}).items()
        ),
        required=required,
        human_only=bool(declaration.get("x-human-only", False)),
        follow_convention=bool(declaration.get("x-follow-convention", False)),
        original_key=key,
    )


def spell_pairs(pairs: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{left}={right}" for left, right in pairs)


def read_pairs(raw: str, *, label_optional: bool) -> tuple[tuple[str, str], ...]:
    """`a=1, b=2` 讀成成對的東西。

    label_optional 是給可選值用的：只寫 `feat` 就以值本身當顯示名稱，因為英文專案
    的標籤本來就等於值，不該逼人多打一次。
    """
    collected: list[tuple[str, str]] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        left, separator, right = piece.partition("=")
        left, right = left.strip(), right.strip()
        if not left:
            raise ValueError(f"「{piece}」左邊是空的。")
        if not separator or not right:
            if not label_optional:
                raise ValueError(f"「{piece}」要寫成 欄位=值。")
            right = left
        collected.append((left, right))
    return tuple(collected)


class FieldFormScreen(Dialog[FieldDraft | None]):
    """一個欄位的內容。新增與修改是同一張表單，差別只在有沒有帶值進來。"""

    BINDINGS = [
        Binding("escape", "close", "關閉"),
        Binding("ctrl+s", "accept", "收下"),
    ]

    ROWS = (
        ("key", "欄位名（備註裡的鍵，例如 change_log）"),
        ("title", "標題（畫面上顯示的名字）"),
        ("prompt", "填寫指示（人與 AI 讀的是同一份）"),
        ("input", f"輸入型別（{' / '.join(INPUT_KINDS)}）"),
        ("choices", "可選值（choice 才有）：feat=功能, fix=錯誤"),
        ("item_url", "每項網址（integer-list 才有，用 {value} 代入）"),
        ("ignore_when", "什麼時候不問這一欄：type=skip"),
    )

    SWITCHES = (
        ("required", "必填"),
        ("human_only", "只能由人填（AI 寫不進去）"),
        ("follow_convention", "commit 前綴對得上可選值時就用它（choice 才有）"),
    )

    def __init__(self, draft: FieldDraft | None = None) -> None:
        super().__init__()
        self._draft = draft or FieldDraft(key="", title="", prompt="", input="text")

    def compose(self) -> ComposeResult:
        with Vertical(id="field-form-box", classes=BOX_CLASS):
            yield Label("欄位" if self._draft.original_key else "新增欄位", id="field-form-heading")
            with VerticalScroll(id="field-form-rows"):
                for name, label in self.ROWS:
                    yield Label(label, classes="field-form-label")
                    yield Input(value=self._value_of(name), id=f"field-form-{name}")
                for name, label in self.SWITCHES:
                    yield Label(label, classes="field-form-label")
                    yield Switch(value=getattr(self._draft, name), id=f"field-form-{name}")
            yield Label("", id="field-form-error", classes="dialog-error")
            yield Label(FORM_HINT, classes="dialog-hint")

    def _value_of(self, name: str) -> str:
        if name in ("choices", "ignore_when"):
            return spell_pairs(getattr(self._draft, name))
        return str(getattr(self._draft, name))

    def on_mount(self) -> None:
        self.query_one("#field-form-key", Input).focus()

    def action_accept(self) -> None:
        collected = {name: self.query_one(f"#field-form-{name}", Input).value.strip()
                     for name, _ in self.ROWS}

        problem = self._problem_with(collected)
        if problem:
            self.query_one("#field-form-error", Label).update(problem)
            return

        try:
            choices = read_pairs(collected["choices"], label_optional=True)
            ignore_when = read_pairs(collected["ignore_when"], label_optional=False)
        except ValueError as error:
            self.query_one("#field-form-error", Label).update(str(error))
            return

        self.dismiss(
            FieldDraft(
                key=collected["key"],
                title=collected["title"],
                prompt=collected["prompt"],
                input=collected["input"],
                choices=choices,
                item_url=collected["item_url"],
                ignore_when=ignore_when,
                required=self._switch("required"),
                human_only=self._switch("human_only"),
                follow_convention=self._switch("follow_convention"),
                original_key=self._draft.original_key,
            )
        )

    def _switch(self, name: str) -> bool:
        return self.query_one(f"#field-form-{name}", Switch).value

    def _problem_with(self, collected: Mapping[str, str]) -> str:
        """宣告檔擋得住的錯就讓宣告檔擋，這裡只擋它擋不住的。"""
        if not collected["key"]:
            return "欄位名不能空著。"
        if not collected["prompt"]:
            return "填寫指示不能空著——沒有它，人與 AI 都不知道這一欄要填什麼。"
        if collected["input"] not in INPUT_KINDS:
            return f"輸入型別只能是 {' / '.join(INPUT_KINDS)}。"
        if collected["input"] == "choice" and not collected["choices"]:
            return "choice 欄位要給可選值。"
        if collected["item_url"] and collected["input"] != "integer-list":
            return "每項網址只有 integer-list 欄位用得上。"
        if self._switch("follow_convention") and collected["input"] != "choice":
            return "「前綴對得上就用它」只有 choice 欄位用得上——要對上的正是那組可選值。"
        return ""

    def action_close(self) -> None:
        self.dismiss(None)


class FieldsScreen(Dialog[FieldPlan | None]):
    """欄位一覽。改完按 ctrl+s 交出一份計畫，這個畫面自己不碰 git 也不寫檔。"""

    BINDINGS = [
        Binding("escape", "close", "關閉"),
        Binding("a", "add", "新增"),
        Binding("e", "edit", "修改"),
        Binding("d", "delete", "刪除"),
        Binding("ctrl+s", "save", "儲存"),
    ]

    def __init__(
        self,
        document: Mapping[str, Any],
        carrying: Callable[[str], int] = lambda _: 0,
    ) -> None:
        super().__init__()
        self._document: dict[str, Any] = {
            **document,
            "properties": dict(document.get("properties", {})),
            "required": list(document.get("required", [])),
        }
        self._carrying = carrying
        self._original_keys = set(self._document["properties"])
        self._renames: list[tuple[str, str]] = []
        self._drops: list[str] = []

    # --- 畫面 ---

    def compose(self) -> ComposeResult:
        with Vertical(id="fields-box", classes=BOX_CLASS):
            yield Label("欄位宣告", id="fields-title")
            yield OptionList(id=LIST_ID)
            yield Label("", id=ERROR_ID, classes="dialog-error")
            yield Label(HINT, classes="dialog-hint")

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one(f"#{LIST_ID}", OptionList).focus()

    def _refresh_list(self, highlight: int = 0) -> None:
        listing = self.query_one(f"#{LIST_ID}", OptionList)
        listing.clear_options()
        listing.add_options([Option(self._row_of(key)) for key in self._keys])
        if self._keys:
            listing.highlighted = min(highlight, len(self._keys) - 1)

    @property
    def _keys(self) -> list[str]:
        return list(self._document["properties"])

    def _row_of(self, key: str) -> str:
        declaration = self._document["properties"][key]
        marks = "".join(
            [
                "*" if key in self._document["required"] else " ",
                "人" if declaration.get("x-human-only") else " ",
            ]
        )
        return f"{marks} {key:<18} {declaration.get('title', key):<10} {declaration.get('x-input', '')}"

    @property
    def _selected(self) -> str | None:
        listing = self.query_one(f"#{LIST_ID}", OptionList)
        if listing.highlighted is None or not self._keys:
            return None
        return self._keys[listing.highlighted]

    # --- 動作 ---

    def action_add(self) -> None:
        self.app.push_screen(FieldFormScreen(), self._take_draft)

    def action_edit(self) -> None:
        key = self._selected
        if key is None:
            return
        draft = draft_of(
            key, self._document["properties"][key], key in self._document["required"]
        )
        self.app.push_screen(FieldFormScreen(draft), self._take_draft)

    def action_delete(self) -> None:
        key = self._selected
        if key is None:
            return
        affected = self._carrying(key) if key in self._original_keys else 0
        question = f"要刪掉「{key}」嗎？"
        if affected:
            question += f"\n有 {affected} 筆既有備註帶著它，會一起被拿掉。"
        self.app.push_screen(ConfirmScreen(question), lambda yes: self._delete(key, yes))

    def _delete(self, key: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        position = self._keys.index(key)
        del self._document["properties"][key]
        if key in self._document["required"]:
            self._document["required"].remove(key)
        if key in self._original_keys:
            self._drops.append(key)
        self._refresh_list(position)

    def _take_draft(self, draft: FieldDraft | None) -> None:
        if draft is None:
            return

        properties = self._document["properties"]
        renamed = draft.original_key is not None and draft.original_key != draft.key

        if draft.key in properties and draft.key != draft.original_key:
            self.query_one(f"#{ERROR_ID}", Label).update(f"已經有一個欄位叫「{draft.key}」了。")
            return

        if renamed:
            properties = {
                (draft.key if key == draft.original_key else key): value
                for key, value in properties.items()
            }
            if draft.original_key in self._original_keys:
                self._renames.append((draft.original_key, draft.key))

        properties[draft.key] = draft.as_declaration()
        self._document["properties"] = properties
        self._sync_required(draft)
        self._refresh_list(self._keys.index(draft.key))

    def _sync_required(self, draft: FieldDraft) -> None:
        required: list[str] = [
            key for key in self._document["required"]
            if key != draft.key and key != draft.original_key
        ]
        if draft.required:
            required.append(draft.key)
        self._document["required"] = required

    def action_save(self) -> None:
        if not self._document["properties"]:
            self.query_one(f"#{ERROR_ID}", Label).update("一個欄位都沒有的宣告收不下。")
            return
        try:
            schema.build_fields(self._document)
        except schema.SchemaDeclarationError as error:
            self.query_one(f"#{ERROR_ID}", Label).update(str(error))
            return

        self.dismiss(
            FieldPlan(
                document=self._document,
                renames=tuple(self._renames),
                drops=tuple(self._drops),
            )
        )

    def action_close(self) -> None:
        self.dismiss(None)
