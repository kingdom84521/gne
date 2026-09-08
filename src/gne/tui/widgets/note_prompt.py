"""填寫備註的問答。

一次只問一題：答過的留成一行掛在上面，當前的問題永遠在最底下，游標就在那裡——跟
命令列一樣，打字時不必往上找東西，也不會因為欄位多就得捲動。問題本身、可選值、
預設值全部從宣告檔衍生，增修欄位不必動這裡。

「這一格有沒有被動過」是刻意記下來的：多行的舊值在單行輸入框裡呈現不了，直接 Enter
就原樣保留，不會被壓成一行。真的要寫多行的內容走 `gne set --from-stdin`。
"""

from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, RadioButton, RadioSet, Static

from ...core import provenance, schema
from ...core.types import NoteDocument
from .. import keys

QUESTION_ID = "prompt-question"
INPUT_ID = "prompt-input"
CHOICES_ID = "prompt-choices"
LOG_ID = "prompt-log"

# 一排最多四個，超過就換行。排法寫在 gne.tcss 的 grid-size 上。
CHOICES_PER_ROW = 4

BLANK = "（空白）"


def _first_line(text: str) -> str:
    head, _, rest = text.partition("\n")
    return f"{head}…" if rest else head


def question_text(field: schema.NoteField, offered: str, existing: bool = False) -> str:
    """一題長什麼樣。

    可選值不寫在問題裡——那是一排選得動的東西（← → 移動、Enter 選定），印成文字
    等於把控制項降級成說明。

    「保留」與「用預設」分得開：已經有備註的是把原值留著，還沒有備註的是用
    .gne/default-note 與 commit 標題推出來的預設值——直接 Enter 會寫進去什麼，要看得見。
    """
    parts = [f"{field.title}?"]
    if field.human_only:
        parts.append("（這一欄由你判斷）")
    if not offered:
        parts.append("（← → 選；沒有預設值）" if field.choices else "（Enter 留空）")
    else:
        verb = "保留" if existing else "用預設"
        parts.append(
            f"（← → 選，Enter {verb} {offered}）"
            if field.choices
            else f"（Enter {verb}：{_first_line(offered)}）"
        )
    return " ".join(parts)


def choice_label(field: schema.NoteField, choice: str) -> str:
    """存的是值、讀的是標籤，所以兩個都給。不用括號——一排四個要塞得下。"""
    return f"{choice} {field.label_of(choice)}"


class ChoiceRow(RadioSet):
    """一排可選值：← → 移動、Enter 選定。

    Enter 一律代表「就這一個」。RadioSet 自己的 enter 是 toggle，選中原本已經選著的
    那一個不會發出 Changed——而「接受預設值」正是最常見的動作，不能沒有反應。
    方向鍵沿用 RadioSet 原本的行為。
    """

    class Picked(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    BINDINGS = [keys.hidden("enter,space", "pick", "選定")]

    def __init__(self, *buttons: RadioButton, default: int = -1) -> None:
        super().__init__(*buttons)
        self._default = default
        self._pointed = False

    def action_next_button(self) -> None:
        """游標落在顯示為已選的那一個上，而不是第一個。

        RadioSet 掛載時會呼叫這個 action 一次來把游標放到第一個選項——那與預設值未必
        是同一個，於是「直接按 Enter」會選到不是預設的東西。攔住那第一次就好：之後
        每一次都是使用者真的在移動。（改在 mount handler 或 refresh 之後動手都會跟
        使用者的按鍵搶時序。）

        預設值由呼叫端傳進來而不是問 pressed_index：RadioSet 是在呼叫這個 action 之後
        才記錄哪一個被按下的，這一刻問它還是 -1。
        """
        if not self._pointed:
            self._pointed = True
            if self._default >= 0:
                self._selected = self._default
                return
        super().action_next_button()

    def action_pick(self) -> None:
        if self._selected is not None:
            self.post_message(self.Picked(self._selected))


def answered_line(field: schema.NoteField, value: object) -> str:
    if schema.is_empty(value):
        return f"{field.title}: {BLANK}"
    if field.input == "choice":
        return f"{field.title}: {value}（{field.label_of(str(value))}）"
    return f"{field.title}: {schema.format_value(field, value)}"


class NotePrompt(Vertical):
    """問答本身不知道 commit 是什麼，只認得欄位。"""

    class Committed(Message):
        pass

    class Cancelled(Message):
        pass

    class ClearRequested(Message):
        pass

    # 都不上快捷鍵列，改列在 ctrl+h 的清單裡（見 keys.hidden）。
    #
    # esc 是「退一層」：手上還有打好的字就先清掉那一格（連按兩次，一次是手滑），
    # 沒有東西可清就退出這一筆的編輯。兩件事分得開，因為「有沒有字可以清」是
    # 看得出來的（見 clearable），不必要求使用者記住兩顆不同的鍵。
    #
    # ctrl+w 留著做同一件取消，給已經按熟的手。priority 不能拿掉——輸入框自己把
    # ctrl+w 綁成「刪掉左邊那個詞」，不搶在它之前就永遠輪不到這裡。代價是輸入框裡
    # 少了那個刪詞鍵，退格與 ctrl+u（清到行首）還在。
    BINDINGS = [
        keys.hidden("ctrl+s", "request_commit", "儲存這筆"),
        keys.hidden("ctrl+w", "request_cancel", "取消（不儲存，回瀏覽）", priority=True),
        keys.hidden("escape", "request_escape", "清空打好的字（連按兩次）；沒字可清就取消"),
    ]

    def __init__(self, **arguments) -> None:
        super().__init__(**arguments)
        self._baseline: dict[str, Any] = {}
        self._answers: dict[str, Any] = {}
        self._index = 0
        self._offered = ""
        self._existing = False
        self._answering: Widget | None = None

    def compose(self) -> ComposeResult:
        # 答過的那幾行不收焦點：點它一下是想看，不是想離開正在回答的那一格。
        yield VerticalScroll(id=LOG_ID, can_focus=False)
        yield Static("", id=QUESTION_ID)
        yield Input(id=INPUT_ID)
        yield Vertical(id=CHOICES_ID)

    # --- 對外 ---

    def start(self, note: NoteDocument, existing: bool = False) -> None:
        """從第一題開始問。原本的內容當預設值，沒答到的題目保留它。

        existing 說的是「這個 commit 本來就有備註」——問句要據此分辨「保留原值」
        與「用預設值」，那是兩件不一樣的事。
        """
        self._baseline = dict(provenance.fields_of(note))
        self._existing = existing
        self._answers = {}
        self._index = 0
        self.query_one(f"#{LOG_ID}", VerticalScroll).remove_children()
        self._ask()

    @property
    def clearable(self) -> bool:
        """有沒有東西可以清。選項題沒有輸入框，空的輸入框也沒有。"""
        return isinstance(self._answering, Input) and bool(self._answering.value)

    @property
    def touched(self) -> bool:
        """正在答的那一格有沒有被動過。

        輸入框一開始就放著預設值，所以「裡面有字」不等於「打過字」——問的是離開會不會
        弄丟使用者自己打的東西，那要跟當初給的那一份比。
        """
        return isinstance(self._answering, Input) and self._answering.value != self._offered

    def clear_answer(self) -> None:
        if isinstance(self._answering, Input):
            self._answering.value = ""

    def focus_answer(self) -> None:
        """把游標放回正在問的那一格。

        回到問答（對話框關掉、或是點回這一區）就該能直接打字，不必再去點準輸入框
        那一行——問題與可選值都在這一塊裡，點哪裡都是同一個意思。
        """
        if self._answering is not None and not self._answering.has_focus:
            self._answering.focus()

    def on_click(self) -> None:
        self.focus_answer()

    def collect_note(self) -> Mapping[str, Any]:
        return schema.strip_empty({**self._baseline, **self._answers})

    @property
    def current_field(self) -> schema.NoteField | None:
        fields = schema.note_fields()
        return fields[self._index] if self._index < len(fields) else None

    @property
    def asking(self) -> bool:
        return self.current_field is not None

    @property
    def question(self) -> str:
        """目前那一題的原文。畫面上顯示的就是這一份。"""
        field = self.current_field
        return question_text(field, self._offered, self._existing) if field else ""

    # --- 問與答 ---

    def _ask(self) -> None:
        self._skip_settled()
        field = self.current_field
        if field is None:
            self.post_message(self.Committed())
            return
        self._offered = schema.format_value(field, self._value_of(field))
        self.query_one(f"#{QUESTION_ID}", Static).update(
            question_text(field, self._offered, self._existing)
        )
        if field.choices:
            self._offer_choices(field)
        else:
            self._offer_line()

    def _offer_line(self) -> None:
        self.query_one(f"#{CHOICES_ID}", Vertical).display = False
        control = self.query_one(f"#{INPUT_ID}", Input)
        control.display = True
        control.value = self._offered
        self._answering = control
        control.focus()

    def _offer_choices(self, field: schema.NoteField) -> None:
        """可選值排成一排選得動的東西，預設落在原本的值上。

        原本的值不在可選範圍內時（舊資料真的有 type: ''）就一個都不選：那時按 Enter
        保留原值，不會被悄悄改成第一個選項。
        """
        self.query_one(f"#{INPUT_ID}", Input).display = False
        holder = self.query_one(f"#{CHOICES_ID}", Vertical)
        holder.display = True
        holder.remove_children()

        current = self._offered
        default = field.choices.index(current) if current in field.choices else -1
        # 拿著剛建好的那一個，不要回頭去 query：remove_children() 不是同步完成的，
        # 上一題的那一排可能還在樹上，query 會撞到兩個。
        row = ChoiceRow(
            *(
                RadioButton(choice_label(field, choice), value=index == default)
                for index, choice in enumerate(field.choices)
            ),
            default=default,
        )
        holder.mount(row)
        self._answering = row
        row.focus()

    def on_choice_row_picked(self, event: ChoiceRow.Picked) -> None:
        """選定就是答完這一題。"""
        event.stop()
        field = self.current_field
        if field is None:
            return
        self._accept(field, field.choices[event.index])

    def _skip_settled(self) -> None:
        """已經被前面的答案決定掉的欄位就不必問了。

        種類選了 skip，這一筆不進 release note，後面幾欄問了也沒有意義——那是宣告檔用
        x-ignore-when 講的，不是這裡寫死的。原本填過的內容留著，只是不再問。
        """
        skipped: list[schema.NoteField] = []
        while (field := self.current_field) is not None and schema.ignored(field, self._so_far()):
            skipped.append(field)
            self._index += 1
        if skipped:
            titles = "、".join(field.title for field in skipped)
            self._log(f"（{schema.ignore_reason(skipped[0])}，不問了：{titles}）")

    def _so_far(self) -> dict[str, Any]:
        return {**self._baseline, **self._answers}

    def _value_of(self, field: schema.NoteField) -> object:
        return self._answers.get(field.key, self._baseline.get(field.key, ""))

    def _log(self, line: str) -> None:
        log = self.query_one(f"#{LOG_ID}", VerticalScroll)
        log.mount(Static(line))
        log.scroll_end(animate=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        field = self.current_field
        if field is None:
            return

        if event.value == self._offered:
            # 一個字都沒動：原值原樣留著，多行的內容不會在這裡被壓平。
            value = self._value_of(field)
        else:
            try:
                value = schema.parse_value(field, event.value)
            except schema.FieldInputError as error:
                self._log(f"✗ {error}")
                self.query_one(f"#{INPUT_ID}", Input).focus()
                return

        self._accept(field, value)

    def _accept(self, field: schema.NoteField, value: object) -> None:
        self._answers[field.key] = value
        self._log(answered_line(field, value))
        self._index += 1
        self._ask()

    def action_request_commit(self) -> None:
        self.post_message(self.Committed())

    def action_request_cancel(self) -> None:
        self.post_message(self.Cancelled())

    def action_request_escape(self) -> None:
        """esc 退一層：先清掉打好的字，沒字可清就退出這一筆。

        清空要連按兩次（那一步在 app 上掛提示），取消不必——取消本來就會問過改動
        要不要留。所以同一顆鍵按下去永遠有反應，不會有「按了沒事發生」的那一刻。
        """
        if self.clearable:
            self.post_message(self.ClearRequested())
            return
        self.post_message(self.Cancelled())
