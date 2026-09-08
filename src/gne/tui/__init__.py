"""互動式編輯器。對外只暴露啟動函式與狀態型別。"""

from ..core.entity import NoteController
from .app import GneApp
from .setup import run_field_setup
from .state import EditorState, seed_for


def run_editor(
    controller: NoteController,
    *,
    revision_range: str | None = None,
    author_email: str | None = None,
    unnoted_only: bool = True,
    ai_only: bool = False,
    only: str | None = None,
    push: bool = True,
    read_only: bool = False,
) -> None:
    GneApp(
        controller,
        revision_range=revision_range,
        author_email=author_email,
        unnoted_only=unnoted_only,
        ai_only=ai_only,
        only=only,
        push=push,
        read_only=read_only,
    ).run()


__all__ = ["EditorState", "GneApp", "run_editor", "run_field_setup", "seed_for"]
