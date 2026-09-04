"""是／否確認框。"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label

from .dialog import BOX_CLASS, BUTTON_KEYS, Dialog

YES = "yes"
NO = "no"

HINT = "← → 選，Enter 確定；Esc 或點對話框外面都是「否」"


class ConfirmScreen(Dialog[bool]):
    OUTSIDE_RESULT = False

    BINDINGS = [
        *BUTTON_KEYS,
        Binding("escape", "answer_no", "取消"),
        Binding("y", "answer_yes", "是"),
        Binding("n", "answer_no", "否"),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box", classes=BOX_CLASS):
            yield Label(self._question, id="confirm-question")
            with Horizontal(id="confirm-actions"):
                yield Button("是 (y)", variant="primary", id=YES)
                yield Button("否 (n)", id=NO)
            yield Label(HINT, classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(f"#{YES}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == YES)

    def action_answer_yes(self) -> None:
        self.dismiss(True)

    def action_answer_no(self) -> None:
        self.dismiss(False)
