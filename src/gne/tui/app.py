"""單畫面 git note 編輯器。

左側是 commit 列表，右側在預覽與表單之間原地切換，左側始終不動。編輯只進暫存，
按 s 才一次寫入並推送——一個 release 幾十筆備註不該產生幾十次 push。

git 操作一律走背景 worker，畫面不會被 fetch 或 push 凍住。
"""

from rich.text import Text
from textual import events, work
from textual.timer import Timer
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, OptionList, Static

from .. import advisor
from ..core import defaults, git, provenance, schema
from ..core.entity import NoteController, NoteError, NoteSyncError
from ..core.types import NoteDocument
from . import keys, session
from .screens import (
    CommitDetailScreen,
    CommitInfoScreen,
    ConfirmScreen,
    DefaultNoteScreen,
    FieldPlan,
    FieldsScreen,
    RangeScreen,
    ShortcutsScreen,
    SuggestionScreen,
)
from .state import EditorState
from .widgets import CommitList, NotePreview, NotePrompt
from .widgets.commit_list import note_state

NOTHING_SELECTED = "（沒有可編輯的 commit）"

# 兩段式按鍵：第一次按只把提示蓋到快捷鍵列上，第二次才真的做。丟掉待寫入的備註或
# 打好的字都是不可逆的，但為它們各開一個對話框又太重。
QUIT_HINT = "再按一次 Ctrl+C 不儲存直接離開"
CLEAR_HINT = "再按一次 Esc 清空輸入"
DOUBLE_PRESS_SECONDS = 3.0

LOADING_TITLE = "讀取 commit 中…"
LOADING_DETAIL = "正在同步 refs/notes 並掃描區間"
LOADING_STATUS = "讀取中…"


STATUS_WORDS = {
    "pending": "已編輯，尚未寫入",
    "ai-generated": "由 AI 產生，待人工確認",
    "saved": "已寫入",
    "untouched": "尚未填寫",
}


def meta_line(commit: git.CommitInfo) -> str:
    return f"{commit.short_hash}  {commit.author} <{commit.author_email}>  {commit.date}"


def commit_info_rows(commit: git.CommitInfo, state: EditorState) -> tuple[tuple[str, str], ...]:
    """置頂那條放不下的東西。分支上的 hash 只在與備註掛載處不同時才有意義。"""
    rows = [("commit", commit.hash)]
    if commit.branch_hash != commit.hash:
        rows.append(("分支上的 commit", commit.branch_hash))
    rows.extend(
        [
            ("作者", commit.author),
            ("Email", commit.author_email),
            ("日期", commit.date),
            ("備註", STATUS_WORDS[note_state(state, commit.hash)]),
        ]
    )
    return tuple(rows)


def heading_for(commit: git.CommitInfo) -> str:
    """詳情畫面的兩行標題。"""
    return f"{commit.subject}\n{meta_line(commit)}"


def status_for(state: EditorState) -> str:
    return f"{len(state.commits)} 筆 commit ｜ {state.pending_count} 筆待寫入"


class GneApp(App[None]):
    CSS_PATH = "gne.tcss"
    TITLE = "Git Note Editor"

    AUTO_FOCUS = "CommitList"

    # Textual 的指令面板不是這個工具的介面（按鍵就那幾顆，ctrl+h 一次列完），它掛的
    # ctrl+p 在 VS Code 裡是 Quick Open 按不到，而且面板自帶的 Quit 會繞過「還有待
    # 儲存」的確認。關掉它比留一條繞過確認的路好。
    ENABLE_COMMAND_PALETTE = False

    # 快捷鍵列上只有第一顆，其餘的鍵都在 ctrl+h 叫出來的清單裡（見 keys.hidden）。
    BINDINGS = [
        # backspace 一起綁：多數終端機把 ctrl+h 送成 backspace 的那個位元組，分得出來的
        # 只有支援 Kitty 鍵盤協定的那些。輸入框自己會吃掉 backspace，打字因此不受影響。
        Binding("ctrl+h,backspace", "show_shortcuts", "快捷鍵", key_display="ctrl+h"),
        # 要按的是 ctrl+shift+q：ctrl+q 在 VS Code 上是「結束 VS Code」，按下去會把編輯器
        # 一起關掉。多數終端機把這兩顆送成同一個位元組（分得出來的只有支援 Kitty 鍵盤協定
        # 的那些），所以兩顆都綁——分不出來的終端機收到的是 ctrl+q，那時也要離開得掉。
        keys.hidden("ctrl+shift+q,ctrl+q", "leave", "離開", key_display="ctrl+shift+q"),
        keys.hidden("ctrl+c", "leave_at_once", "不儲存直接離開（連按兩次）"),
        # ctrl+shift+w 只有支援 Kitty 鍵盤協定的終端機分得出來，其餘會當成 ctrl+w
        # （＝編輯中的「取消」）。分不出來的終端機請用連按兩次 ctrl+c。
        keys.hidden("ctrl+shift+w", "leave_now", "強制關閉"),
        keys.hidden("ctrl+o", "show_commit_info", "commit 資訊"),  # Ctrl+I 見 on_key
        keys.hidden("f1", "show_detail", "檔案與 diff"),
        keys.hidden("ctrl+r", "change_range", "改看哪一段"),
        keys.hidden("ctrl+d", "edit_default_note", "新備註的起點"),
        keys.hidden("ctrl+f", "edit_fields", "欄位宣告"),
    ]

    state: reactive[EditorState] = reactive(EditorState, always_update=True)
    editing: reactive[bool] = reactive(False)
    loading_commits: reactive[bool] = reactive(True, always_update=True)

    def __init__(
        self,
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
        super().__init__()
        self._read_only = read_only
        self._controller = controller
        self._revision_range = revision_range
        self._author_email = author_email
        self._unnoted_only = unnoted_only
        self._ai_only = ai_only
        self._only = only
        self._push = push
        self._armed_action: str | None = None
        self._armed_timer: Timer | None = None

    # --- 組裝 ---

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="commit-pane"):
                yield CommitList(id="commits")
            with Vertical(id="pane"):
                yield Static("", id="commit-subject")
                yield NotePreview(id="preview")
                yield NotePrompt(id="prompt")
        yield Static("", id="status")
        yield Static("", id="key-hint")
        yield Footer()

    def get_key_display(self, binding: Binding) -> str:
        """快捷鍵列與快捷鍵一覽用同一種寫法。怎麼寫見 keys.spelled_out。"""
        return keys.spelled_out(binding)

    def on_mount(self) -> None:
        if self._read_only:
            self.sub_title = self.READ_ONLY_REASON
        pane = self.commit_pane
        pane.styles.width = self.commit_list.required_width + pane.gutter.width
        self.reload_commits()

    @property
    def commit_pane(self) -> Vertical:
        """承載列表的容器。寬度掛在這裡——loading 中的 widget 版面會歸零，
        寬度若掛在列表上，讀取期間左側就會塌掉。"""
        return self.query_one("#commit-pane", Vertical)

    @property
    def commit_list(self) -> CommitList:
        return self.query_one(CommitList)

    @property
    def prompt(self) -> NotePrompt:
        return self.query_one(NotePrompt)

    @property
    def selected_hash(self) -> str | None:
        return self.commit_list.selected_hash

    # --- 反應 ---

    def watch_state(self, state: EditorState) -> None:
        if not self.is_running:
            return
        self.commit_list.display_state(state)
        self.refresh_chrome()

    def watch_loading_commits(self, loading: bool) -> None:
        if not self.is_running:
            return
        self.commit_list.loading = loading
        self.refresh_chrome()

    def refresh_chrome(self) -> None:
        self.query_one("#status", Static).update(
            LOADING_STATUS if self.loading_commits else status_for(self.state)
        )
        self.refresh_pane()

    def watch_editing(self, editing: bool) -> None:
        if not self.is_running:
            return
        self.query_one(NotePreview).display = not editing
        self.prompt.display = editing

    def on_option_list_option_highlighted(self, _: OptionList.OptionHighlighted) -> None:
        self.refresh_pane()

    def on_option_list_option_selected(self, _: OptionList.OptionSelected) -> None:
        self.action_start_edit()

    def on_commit_list_detail_requested(self, _: CommitList.DetailRequested) -> None:
        self.action_show_detail()

    def on_commit_list_accept_requested(self, _: CommitList.AcceptRequested) -> None:
        self.action_accept()

    def on_commit_list_accept_all_requested(self, _: CommitList.AcceptAllRequested) -> None:
        self.action_accept_all()

    def on_commit_list_advice_requested(self, _: CommitList.AdviceRequested) -> None:
        self.action_ask_advice()

    def on_commit_list_save_requested(self, _: CommitList.SaveRequested) -> None:
        self.action_save_all()

    def on_commit_list_reload_requested(self, _: CommitList.ReloadRequested) -> None:
        self.action_reload()

    def on_commit_list_leave_requested(self, _: CommitList.LeaveRequested) -> None:
        self.action_leave()

    def on_note_prompt_committed(self, _: NotePrompt.Committed) -> None:
        self.action_commit_edit()

    def on_note_prompt_cancelled(self, _: NotePrompt.Cancelled) -> None:
        self.action_cancel_edit()

    def on_note_prompt_clear_requested(self, _: NotePrompt.ClearRequested) -> None:
        """清空打好的字要按兩次 Esc：一次是手滑，兩次才是本意。"""
        if self.confirmed_twice("clear_answer", CLEAR_HINT):
            self.prompt.clear_answer()

    def refresh_pane(self) -> None:
        if self.loading_commits:
            self.query_one("#commit-subject", Static).update(LOADING_TITLE)
            self.query_one(NotePreview).display_hint(LOADING_DETAIL)
            return

        revision = self.selected_hash
        commit = self.state.commit_of(revision) if revision else None
        self.query_one("#commit-subject", Static).update(
            commit.subject if commit else NOTHING_SELECTED
        )
        if revision is not None:
            self.query_one(NotePreview).display_note(self.state.written_note_of(revision))

    # --- 載入 ---

    def reload_commits(self) -> None:
        self.loading_commits = True
        self._fetch_commits()

    @work(thread=True, exclusive=True, group="load")
    def _fetch_commits(self) -> None:
        try:
            loaded = session.load(
                self._controller,
                self._revision_range,
                author_email=self._author_email,
                unnoted_only=self._unnoted_only,
                ai_only=self._ai_only,
                only=self._only,
            )
        except git.RangeNotGiven:
            # 第一次進來沒有可以沿用的區間：問，而不是把人踢出去重下一次命令列。
            self.call_from_thread(self.action_change_range)
            return
        except (NoteSyncError, git.GitError, schema.SchemaNotDeclared) as error:
            self.call_from_thread(self._loading_failed, str(error))
            return
        self.call_from_thread(self._apply_loaded, loaded)

    def _loading_failed(self, reason: str) -> None:
        self.loading_commits = False
        self.notify(reason, severity="error")

    def _apply_loaded(self, loaded: EditorState) -> None:
        self.state = loaded
        self.loading_commits = False
        notice = self._controller.take_sync_notice()
        if notice:
            self.notify(notice)
        self.commit_list.focus()
        if self._only is not None and loaded.commits:
            self.action_start_edit()

    # --- 唯讀 ---

    READ_ONLY_REASON = "唯讀"
    READ_ONLY_NOTICE = "唯讀模式：這個動作會改東西，所以做不了。"

    def _refused_while_read_only(self) -> bool:
        """會改東西的動作都先問過這裡。

        唯讀不是把鍵拿掉：鍵還在、清單上看得到、按下去會說為什麼——不然人只會覺得
        壞了。ctrl+h 的清單也把這幾條標成暗的。
        """
        if not self._read_only:
            return False
        self.notify(self.READ_ONLY_NOTICE, severity="warning")
        return True

    # --- 專案自己的設定：區間、起點、欄位 ---

    def action_change_range(self) -> None:
        self.push_screen(RangeScreen(self._current_range()), self._take_range)

    def _current_range(self) -> str | None:
        """畫面上先給現在這一段，改的人通常只動其中一端。"""
        if self._revision_range:
            return self._revision_range
        try:
            return git.remembered_range()
        except git.GitError:
            return None

    def _take_range(self, wanted: str | None) -> None:
        if wanted is None or wanted == self._revision_range:
            return
        self._revision_range = wanted
        self.reload_commits()

    def action_edit_default_note(self) -> None:
        if self._refused_while_read_only():
            return
        try:
            current = defaults.default_note()
        except (schema.NoteValidationError, schema.SchemaNotDeclared) as error:
            self.notify(str(error), severity="error")
            return
        self.push_screen(DefaultNoteScreen(current), self._take_default_note)

    def _take_default_note(self, document: dict[str, object] | None) -> None:
        if document is None:
            return
        try:
            path = defaults.save_default_note(dict(document))
        except (schema.NoteValidationError, git.GitError, OSError) as error:
            self.notify(str(error), severity="error")
            return
        self.notify(f"已寫入 {path.name}")
        self.reload_commits()

    def action_edit_fields(self) -> None:
        if self._refused_while_read_only():
            return
        try:
            document = schema.load_schema()
        except (schema.SchemaNotDeclared, schema.SchemaDeclarationError) as error:
            self.notify(str(error), severity="error")
            return
        self.push_screen(FieldsScreen(document, self._notes_carrying), self._take_field_plan)

    def _notes_carrying(self, key: str) -> int:
        """刪一個欄位之前要講得出影響幾筆。問不到就說 0，畫面不會因此擋人。"""
        try:
            return len(self._controller.notes_carrying(key))
        except (NoteError, git.GitError):
            return 0

    def _take_field_plan(self, plan: FieldPlan | None) -> None:
        if plan is None:
            return
        if not plan.touches_existing_notes:
            self._apply_field_plan(plan)
            return
        self.push_screen(
            ConfirmScreen(self._migration_question(plan)),
            lambda yes: self._apply_field_plan(plan) if yes else None,
        )

    def _migration_question(self, plan: FieldPlan) -> str:
        lines = ["這次改動會一起改寫既有的備註："]
        lines += [f"　{old} → {new}" for old, new in plan.renames]
        lines += [f"　拿掉 {key}" for key in plan.drops]
        lines.append("要繼續嗎？")
        return "\n".join(lines)

    @work(thread=True, exclusive=True, group="fields")
    def _apply_field_plan(self, plan: FieldPlan) -> None:
        """先改備註再寫宣告。

        反過來的話，中間那一刻宣告已經換了、備註還是舊的，這時候任何一次讀取都會
        整批驗證失敗——那正是這條路要避免的事。
        """
        try:
            for old_key, new_key in plan.renames:
                self._controller.rename_field(old_key, new_key)
            for key in plan.drops:
                self._controller.drop_field(key)
            schema.save_schema(plan.document)
        except (NoteError, NoteSyncError, git.GitError, schema.SchemaDeclarationError) as error:
            self.call_from_thread(self.notify, str(error), severity="error")
            return
        self.call_from_thread(self._fields_applied)

    def _fields_applied(self) -> None:
        self.notify("欄位宣告已更新")
        self.reload_commits()

    # --- 編輯 ---

    def action_start_edit(self) -> None:
        """先讓問答顯示出來再開始問：Textual 不能把焦點放在看不見的 widget 上。"""
        if self._refused_while_read_only():
            return
        revision = self.selected_hash
        if revision is None:
            return
        self.editing = True
        self.prompt.start(self.state.note_of(revision), existing=self.state.is_noted(revision))

    def _collect(self) -> dict[str, object]:
        """答過的疊在原內容上。每一題在當下就驗過，這裡不會再失敗。"""
        return dict(self.prompt.collect_note())

    def action_commit_edit(self) -> None:
        revision = self.selected_hash
        if revision is None:
            return
        self.state = self.state.staged(revision, self._collect())
        self._leave_edit()
        if self._only is not None:
            self.action_save_all()

    def action_cancel_edit(self) -> None:
        revision = self.selected_hash
        if revision is None:
            return
        # 只比欄位：AI 記號不是使用者打的，不能拿它冒充「這一筆改過了」。
        if self._collect() == provenance.fields_of(self.state.note_of(revision)):
            self._leave_edit()
            return
        self.push_screen(ConfirmScreen("這一筆改過了，要儲存嗎?"), self._finish_cancel)

    def _finish_cancel(self, keep: bool | None) -> None:
        revision = self.selected_hash
        if keep and revision is not None:
            self.state = self.state.staged(revision, self._collect())
        self._leave_edit()

    def _leave_edit(self) -> None:
        self.editing = False
        self.commit_list.focus()

    # --- 用預設內容填 ---

    def action_accept(self) -> None:
        """不進問答就把預設內容填進去。右側顯示的就是要寫進去的東西。

        絕大多數的備註是「知道有這筆 commit、它不進 release note」，那個值 .gne/default-note
        與 commit 標題就說得出來，逐題按過去只是手續。
        """
        if self._refused_while_read_only():
            return
        revision = self.selected_hash
        if revision is None:
            return
        self.state = self.state.staged(revision, self.state.note_of(revision))

    def _acceptable(self) -> list[str]:
        """還沒有人（或 AI）表態過的那些。已經有備註的不在此列——那是別人下過的判斷。"""
        return [
            commit.hash
            for commit in self.state.commits
            if not self.state.is_noted(commit.hash) and not self.state.is_edited(commit.hash)
        ]

    def action_accept_all(self) -> None:
        if self._refused_while_read_only():
            return
        waiting = self._acceptable()
        if not waiting:
            self.notify("沒有可以填的：列表上的每一筆都已經有備註或已經編輯過了。")
            return
        self.push_screen(
            ConfirmScreen(f"要把 {len(waiting)} 筆全部用預設內容填起來嗎?"), self._finish_accept_all
        )

    def _finish_accept_all(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        state = self.state
        for revision in self._acceptable():
            state = state.staged(revision, state.note_of(revision))
        self.state = state

    # --- 問顧問 ---

    def action_ask_advice(self) -> None:
        """對話框先開起來再去問：問一次要幾十秒，不能讓畫面沒有反應。"""
        if self._refused_while_read_only():
            return
        revision = self.selected_hash
        commit = self.state.commit_of(revision) if revision else None
        if commit is None:
            return
        screen = SuggestionScreen(commit.subject)
        self.push_screen(screen, self._take_advice)
        self.fetch_advice(screen, commit)

    @work(thread=True, exclusive=True, group="advice")
    def fetch_advice(self, screen: SuggestionScreen, commit: git.CommitInfo) -> None:
        try:
            suggestion = advisor.ask(commit, self.state.note_of(commit.hash))
        except advisor.AdvisorError as error:
            self.call_from_thread(screen.show_problem, str(error))
            return
        self.call_from_thread(screen.show_suggestion, suggestion)

    def _take_advice(self, note: NoteDocument | None) -> None:
        """儲存建議＝把它疊在這一筆現有的內容上，成為待寫入的一筆。

        人按下那一刻它就是人填的備註：AI 記號不會跟著進來（fields_of 已經拆掉），
        因為看過理由與程式碼之後才儲存，那個判斷是人的。
        """
        revision = self.selected_hash
        if note is None or revision is None:
            return
        merged = {**provenance.fields_of(self.state.note_of(revision)), **dict(note)}
        self.state = self.state.staged(revision, merged)

    # --- 寫入 ---

    def action_save_all(self) -> None:
        if self._refused_while_read_only():
            return
        if self.state.pending_count == 0:
            self.notify("沒有待寫入的備註。")
            return
        self.save_pending_notes()

    @work(thread=True, exclusive=True, group="save")
    def save_pending_notes(self) -> None:
        try:
            outcome = session.save_pending(self.state, self._controller, push=self._push)
        except (NoteError, NoteSyncError, git.GitError) as error:
            self.call_from_thread(self.notify, str(error), severity="error")
            return
        self.call_from_thread(self._apply_saved, outcome)

    def _apply_saved(self, outcome: session.SaveOutcome) -> None:
        self.state = outcome.state
        if outcome.written:
            self.notify(f"已寫入 {len(outcome.written)} 筆備註。")
        if outcome.sync_failure:
            self.notify(f"已寫入本機，但沒有推送：{outcome.sync_failure}", severity="warning")
        for revision, reason in outcome.failures.items():
            self.notify(f"{revision[: git.SHORT_HASH_LENGTH]}：{reason}", severity="error")

    # --- 重新整理與離開 ---

    def action_reload(self) -> None:
        if self.state.pending_count:
            self.push_screen(
                ConfirmScreen(f"還有 {self.state.pending_count} 筆沒寫入，重新整理會丟掉。要繼續嗎?"),
                self._finish_reload,
            )
            return
        self.reload_commits()

    def _finish_reload(self, confirmed: bool | None) -> None:
        if confirmed:
            self.reload_commits()

    def confirmed_twice(self, action: str, hint: str) -> bool:
        """兩段式按鍵：第一次按只把提示掛上去並回傳 False，三秒內第二次才回傳 True。

        中間按了別的兩段式按鍵就重新開始——掛著的提示永遠只說一件事。
        """
        armed = self._armed_action == action
        self._disarm()
        if armed:
            return True
        self._armed_action = action
        self._armed_timer = self.set_timer(DOUBLE_PRESS_SECONDS, self._disarm)
        self.query_one("#key-hint", Static).update(hint)
        self._show_hint(True)
        return False

    def _disarm(self) -> None:
        if self._armed_timer is not None:
            self._armed_timer.stop()
        self._armed_timer = None
        self._armed_action = None
        self._show_hint(False)

    def _show_hint(self, showing: bool) -> None:
        """提示蓋在快捷鍵列上，不另外佔一行——版面不會因為按了一次而跳。"""
        self.query_one("#key-hint", Static).display = showing
        self.query_one(Footer).display = not showing

    def action_leave_at_once(self) -> None:
        """連按兩次 ctrl+c 就走，不寫入任何東西。"""
        if self.confirmed_twice("leave_at_once", QUIT_HINT):
            self.exit()

    def action_leave_now(self) -> None:
        """強制關閉：不問、不寫入，一按就結束。"""
        self.exit()

    def action_leave(self) -> None:
        if self.state.pending_count:
            self.push_screen(
                ConfirmScreen(f"還有 {self.state.pending_count} 筆沒寫入，確定離開嗎?"),
                self._finish_leave,
            )
            return
        self.exit()

    def _finish_leave(self, confirmed: bool | None) -> None:
        if confirmed:
            self.exit()

    # --- 快捷鍵一覽 ---

    def action_show_shortcuts(self) -> None:
        """完整的快捷鍵清單。內容從真正掛著的 Binding 衍生，不另外維護一份。"""
        self.push_screen(
            ShortcutsScreen(
                keys.sections(
                    browse=CommitList.BINDINGS,
                    editing=NotePrompt.BINDINGS,
                    anywhere=type(self).BINDINGS,
                    detail=CommitDetailScreen.BINDINGS,
                    unavailable=self.unavailable_keys(),
                )
            )
        )

    WRITING_ACTIONS = (
        "select",
        "request_accept",
        "request_accept_all",
        "request_save",
        "request_advice",
        "edit_default_note",
        "edit_fields",
    )

    def unavailable_keys(self) -> dict[str, str]:
        """現在按了也做不了事的鍵。

        問顧問要先有顧問可問——GNE_ADVISOR 沒設就是沒有。唯讀時則是每一顆會改東西的鍵。
        """
        if self._read_only:
            return {action: self.READ_ONLY_REASON for action in self.WRITING_ACTIONS}
        return {} if advisor.configured() else {"request_advice": "未設定"}

    # --- 詳情 ---

    def on_key(self, event: events.Key) -> None:
        """Ctrl+I 也叫得出 commit 資訊。

        終端機把 Tab 與 Ctrl+I 送成同一個位元組，Textual 因此把 ctrl+i 掛成 tab 的別名——
        綁在 BINDINGS 上會連 Tab 一起觸發，編輯模式的欄位切換就毀了。這裡只認
        event.key 恰好是 ctrl+i 的情況：Tab 的 event.key 永遠是 tab，不會誤中。
        真正的 Ctrl+I 只有支援 Kitty 鍵盤協定的終端機送得出來，其餘請用 Ctrl+O。
        """
        if event.key == "ctrl+i":
            event.stop()
            self.action_show_commit_info()

    def action_show_commit_info(self) -> None:
        """對話框先開起來再去查：git show 要跑一下，按鍵不能看起來沒有反應。"""
        revision = self.selected_hash
        commit = self.state.commit_of(revision) if revision else None
        if commit is None:
            return
        screen = CommitInfoScreen(commit_info_rows(commit, self.state))
        self.push_screen(screen)
        self.load_commit_show(screen, commit)

    @work(thread=True, exclusive=True, group="info")
    def load_commit_show(self, screen: CommitInfoScreen, commit: git.CommitInfo) -> None:
        """git show 看的是分支上的那一筆——備註可能掛在本地沒有的 cherry-pick 來源上。

        ANSI 也在這裡轉成畫得出來的東西：幾千行的 diff 轉一次要一百毫秒，
        擺在主執行緒上畫面會頓一下。
        """
        try:
            shown = Text.from_ansi(git.commit_show(commit.branch_hash))
        except git.GitError as error:
            self.call_from_thread(screen.show_problem, str(error))
            return
        self.call_from_thread(screen.show_commit, shown)

    def action_show_detail(self) -> None:
        revision = self.selected_hash
        if revision is None:
            return
        commit = self.state.commit_of(revision)
        if commit is not None:
            self.load_detail(commit)

    @work(thread=True, exclusive=True, group="detail")
    def load_detail(self, commit: git.CommitInfo) -> None:
        try:
            files = "\n".join(git.commit_files(commit.branch_hash))
            diff = git.commit_diff(commit.branch_hash)
        except git.GitError as error:
            self.call_from_thread(self.notify, str(error), severity="error")
            return
        self.call_from_thread(
            self.push_screen, CommitDetailScreen(heading_for(commit), files, diff)
        )
