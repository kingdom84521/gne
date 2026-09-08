"""改欄位宣告的畫面。

宣告檔是這個工具唯一的設定，以前只能手改 JSON——還得先知道 x-input、x-prompt、
x-ignore-when 是什麼。對只設定一次的專案來說那是一次性的成本，對其他人則是入口。

草稿與計畫的定義在 core.fields：命令列走的是同一份，所以畫面上做得到的事與
`gne schema add/edit/remove` 做得到的事一樣多。
"""

import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Switch
from textual.widgets.option_list import Option

from ...core import schema
from ...core.fields import (
    INPUT_KINDS,
    FieldDraft,
    FieldPlan,
    draft_of,
    read_pairs,
    spell_pairs,
)
from .confirm import ConfirmScreen
from .dialog import BOX_CLASS, CLOSE_HINT, Dialog

KEY_COLUMN = 18
TITLE_COLUMN = 12


def display_width(text: str) -> int:
    """一段文字在終端機上佔幾格。中文字佔兩格，所以不能拿字數當寬度。"""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def padded(text: str, width: int) -> str:
    """補到 width 格寬。用 f-string 的 :<n 會拿字數當格數，中文標題就對不齊。"""
    return text + " " * max(0, width - display_width(text))


LIST_ID = "fields-list"
ERROR_ID = "fields-error"

HINT = f"a 新增 ｜ e 修改 ｜ d 刪除 ｜ ctrl+s 儲存；{CLOSE_HINT}"
FORM_HINT = f"ctrl+s 收下這一欄；{CLOSE_HINT}"


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
        explanation: str = "",
    ) -> None:
        super().__init__()
        self._explanation = explanation
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
            if self._explanation:
                yield Label(self._explanation, classes="dialog-explanation")
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
        marks = padded(
            ("*" if key in self._document["required"] else " ")
            + ("人" if declaration.get("x-human-only") else " "),
            4,
        )
        return (
            f"{marks}{padded(key, KEY_COLUMN)}"
            f"{padded(declaration.get('title', key), TITLE_COLUMN)}"
            f"{declaration.get('x-input', '')}"
        )

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
