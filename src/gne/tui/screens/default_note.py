"""編輯新備註的起點。

`.gne/default-note` 以前只能手改 YAML。在一個專案裡設一次就不再動的地方無所謂，
但欄位本來就因專案而異，預設值也就跟著變成會動的東西——會動的東西要有地方改。

這裡照宣告檔長出表單：欄位有幾個就有幾格，值怎麼解析與 CLI 旗標共用同一份規則
（schema.parse_value），所以不會出現「畫面收得下、寫進去卻不合法」的值。
"""

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Label

from ...core import schema
from .dialog import BOX_CLASS, CLOSE_HINT, Dialog

TITLE = "新備註的起點"
EXPLANATION = "每一筆還沒填的備註從這些值開始。留空的欄位不寫進去。"
HINT = f"ctrl+s 儲存；{CLOSE_HINT}"

ERROR_ID = "default-note-error"


def _field_input_id(key: str) -> str:
    return f"default-field-{key}"


class DefaultNoteScreen(Dialog[dict[str, Any] | None]):
    """回傳要存成起點的那一份文件；取消就回 None。"""

    BINDINGS = [
        Binding("escape", "close", "關閉"),
        Binding("ctrl+s", "save", "儲存"),
    ]

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="default-note-box", classes=BOX_CLASS):
            yield Label(TITLE, id="default-note-title")
            yield Label(EXPLANATION, classes="dialog-explanation")
            with VerticalScroll(id="default-note-fields"):
                for field in schema.note_fields():
                    yield Label(self._label_of(field), classes="default-note-label")
                    yield Input(
                        value=schema.format_value(field, self._current.get(field.key, "")),
                        placeholder=self._placeholder_of(field),
                        id=_field_input_id(field.key),
                    )
            yield Label("", id=ERROR_ID, classes="dialog-error")
            yield Label(HINT, classes="dialog-hint")

    def _label_of(self, field: schema.NoteField) -> str:
        return f"{field.title}（{field.key}）"

    def _placeholder_of(self, field: schema.NoteField) -> str:
        """選項題把可選值寫在提示裡——起點沒有問答那一排可以按。"""
        if field.choices:
            return " / ".join(field.choices)
        if field.input == "integer-list":
            return "以逗號分隔的數字"
        return ""

    def on_mount(self) -> None:
        first = self.query(Input).first()
        if first is not None:
            first.focus()

    def action_save(self) -> None:
        try:
            document = self._collected()
        except schema.FieldInputError as error:
            self.query_one(f"#{ERROR_ID}", Label).update(str(error))
            return

        try:
            schema.validate_partial(document)
        except schema.NoteValidationError as error:
            self.query_one(f"#{ERROR_ID}", Label).update(str(error))
            return

        self.dismiss(document)

    def _collected(self) -> dict[str, Any]:
        """空的欄位不進去：起點是「從哪裡開始」，不是一筆填好的備註。"""
        document: dict[str, Any] = {}
        for field in schema.note_fields():
            raw = self.query_one(f"#{_field_input_id(field.key)}", Input).value.strip()
            if not raw:
                continue
            document[field.key] = schema.parse_value(field, raw)
        return document

    def action_close(self) -> None:
        self.dismiss(None)
