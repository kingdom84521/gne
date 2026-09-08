"""gne init 的問答。

第一次在一個 repo 用 gne，要先講出這個專案的 release note 要記哪些欄位。那件事沒有
通用答案，所以 init 不塞一份別人的欄位給你——它開這個畫面問你，用的是跟 `Ctrl+F`
完全一樣的表單，所以之後改欄位不必再學一次。
"""

from textual.app import App

from ..core import schema
from .screens import FieldPlan, FieldsScreen


class FieldSetupApp(App[FieldPlan | None]):
    """只有欄位一覽的畫面。收下的是一份計畫，寫檔由呼叫端做。"""

    CSS_PATH = "gne.tcss"
    TITLE = "gne init"
    ENABLE_COMMAND_PALETTE = False

    EXPLANATION = (
        "這個專案的 release note 要記哪些欄位？按 a 一欄一欄加，加完 ctrl+s 寫入。\n"
        "之後要改，用 gne 裡的 ctrl+f，同一張表單。"
    )

    def on_mount(self) -> None:
        self.push_screen(
            FieldsScreen(schema.blank_declaration(), explanation=self.EXPLANATION),
            self.exit,
        )


def run_field_setup() -> FieldPlan | None:
    """問完回傳計畫；中途離開回 None。"""
    return FieldSetupApp().run()
