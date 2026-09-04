"""右側的唯讀備註呈現。文字排版沿用 render.note_as_text，不另立一套。"""

from textual.widgets import Static

from ... import render
from ...core.types import NoteDocument

NOTHING_WRITTEN = "（尚未填寫）"


class NotePreview(Static):
    def display_note(self, note: NoteDocument) -> None:
        self.update(render.note_as_text(note) or NOTHING_WRITTEN)

    def display_hint(self, hint: str) -> None:
        """還沒有 commit 可看時用——不能拿「尚未填寫」冒充。"""
        self.update(hint)
