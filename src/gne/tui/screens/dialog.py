"""對話框的共通行為。

終端機沒有「把背景變暗、暫時點不動」這種東西，但 Textual 會把螢幕疊起來合成：
`ModalScreen` 預設的底色帶 alpha，下層畫面因此整片壓暗。壓暗加上「點外面就關掉」，
是那個概念在文字介面裡最接近的表達——子類別不要覆蓋 background，否則暗化會消失。

對話框本體要掛上 dialog-box class，點擊落在它以外的地方就關閉。
"""

from textual import events
from textual.binding import Binding
from textual.screen import ModalScreen

BOX_CLASS = "dialog-box"

CLOSE_HINT = "Esc 關閉，或點對話框外面"
SCROLL_HINT = f"{CLOSE_HINT} ｜ ↑ ↓ 捲動"

# 有按鈕的對話框都用同一組移動鍵：`←` `→` 選、`Enter` 確定，跟問答那一排可選值一樣。
# Textual 內建的 tab／shift+tab 也還在，只是沒有人會為了兩顆按鈕去按 tab。
BUTTON_KEYS = (
    Binding("left", "app.focus_previous", "上一個", show=False),
    Binding("right", "app.focus_next", "下一個", show=False),
)


class Dialog[ResultType](ModalScreen[ResultType]):
    OUTSIDE_RESULT = None
    """點對話框外面關閉時回傳的結果。"""

    def still_open(self, selector: str) -> bool:
        """背景查完才回填的內容，回來時對話框未必還在——關掉了就沒有人在等這個答案。"""
        return self.is_attached and bool(self.query(selector))

    def on_click(self, event: events.Click) -> None:
        inside = any(
            event.screen_offset in box.region for box in self.query(f".{BOX_CLASS}")
        )
        if not inside:
            self.dismiss(self.OUTSIDE_RESULT)
