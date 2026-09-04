"""AI 建議：填什麼、為什麼、看哪一段程式碼得出來的。

判斷仍然是人的。這個畫面只把三件事擺在一起——建議的值、理由、以及理由對應的程式碼
位置（附 GitLab 連結，點過去看那幾行）——好讓那個判斷有依據可看，而不是接受一份
不知道從哪裡來的答案。儲存之後它就是人填的備註，不帶任何記號。
"""

from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from ... import advisor, render
from ...core import schema
from .dialog import BOX_CLASS, BUTTON_KEYS, CLOSE_HINT, Dialog

ACCEPT = "accept-suggestion"
CLOSE = "close-suggestion"

ASKING = "詢問顧問中…"


def suggestion_text(suggestion: advisor.Suggestion) -> str:
    """建議、理由、依據。空的段落不留標題——沒有理由就別假裝有。"""
    known = schema.field_by_key()
    blocks: list[str] = []

    filled = [
        f"{known[key].title}：{render.display_value(known[key], value)}"
        for key, value in suggestion.note.items()
        if key in known and not schema.is_empty(value)
    ]
    blocks.append("\n".join(filled) if filled else "（顧問沒有給出任何欄位值）")

    if suggestion.reason:
        blocks.append("理由\n" + suggestion.reason)

    if suggestion.evidence:
        lines: list[str] = []
        for item in suggestion.evidence:
            where = f"{item.path}:{item.lines}" if item.lines else item.path
            lines.append(f"· {where}" + (f"\n  {item.url}" if item.url else ""))
        blocks.append("依據\n" + "\n".join(lines))

    if suggestion.ignored:
        blocks.append("已忽略的欄位（未宣告或只能由人工填）：" + "、".join(suggestion.ignored))

    return "\n\n".join(blocks)


class SuggestionScreen(Dialog[Mapping[str, Any] | None]):
    """儲存時回傳建議的備註內容，關閉時回傳 None。"""

    BINDINGS = [
        *BUTTON_KEYS,
        Binding("escape", "close", "關閉"),
        Binding("y", "accept", "儲存", show=False),
    ]

    def __init__(self, heading: str) -> None:
        super().__init__()
        self._heading = heading
        self._note: Mapping[str, Any] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="suggestion-box", classes=BOX_CLASS):
            yield Label("AI 建議", classes="dialog-title")
            yield Static(self._heading, id="suggestion-heading")
            with VerticalScroll(id="suggestion-scroll"):
                yield Static(ASKING, id="suggestion-body")
            with Horizontal(id="suggestion-actions"):
                yield Button("儲存建議 (y)", variant="primary", id=ACCEPT)
                yield Button("關閉 (esc)", id=CLOSE)
            yield Label(CLOSE_HINT, classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(f"#{ACCEPT}", Button).display = False

    def show_suggestion(self, suggestion: advisor.Suggestion) -> None:
        if not self.still_open("#suggestion-body"):
            return
        self._note = suggestion.note
        self.query_one("#suggestion-body", Static).update(suggestion_text(suggestion))
        accept = self.query_one(f"#{ACCEPT}", Button)
        accept.display = bool(suggestion.note)
        if suggestion.note:
            accept.focus()

    def show_problem(self, reason: str) -> None:
        """問不到就把原因原樣說出來，不要拿空建議冒充答案。"""
        if not self.still_open("#suggestion-body"):
            return
        self._note = None
        self.query_one("#suggestion-body", Static).update(reason)
        self.query_one(f"#{ACCEPT}", Button).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == ACCEPT:
            self.action_accept()
            return
        self.dismiss(None)

    def action_accept(self) -> None:
        if self._note:
            self.dismiss(self._note)

    def action_close(self) -> None:
        self.dismiss(None)
