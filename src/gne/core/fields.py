"""一個欄位的可編輯形式，以及「改了宣告，既有備註要跟著做什麼」。

這裡不是畫面也不是命令列的東西：`Ctrl+F` 的表單與 `gne schema add/edit/remove` 收的是
同一份草稿、產出同一份計畫，所以兩條路能表達的事一樣多，不會有一邊做得到一邊做不到。

刪欄位與改欄位名不只是改宣告：宣告的 additionalProperties 是 false，既有備註裡那個欄位
不跟著改，下一次讀取就整批驗證失敗。所以產出的不是一份新宣告，而是一份計畫——備註先改完，
宣告才落地。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import schema

INPUT_KINDS = ("text", "multiline", "integer-list", "choice")


@dataclass(frozen=True)
class FieldPlan:
    """改完的宣告，以及既有備註要跟著做的事。"""

    document: dict[str, Any]
    renames: tuple[tuple[str, str], ...] = ()
    drops: tuple[str, ...] = ()

    @property
    def touches_existing_notes(self) -> bool:
        return bool(self.renames or self.drops)


@dataclass
class FieldDraft:
    """表單收到的一個欄位。

    可選值與「什麼時候不問」都是成對的東西（值對標籤、欄位對值），表單裡各佔一格，
    寫成 `feat=功能, fix=錯誤`——一個 choice 欄位有幾個可選值不固定，做成幾格輸入
    就得在打字中途重畫表單。
    """

    key: str
    title: str
    prompt: str
    input: str
    choices: tuple[tuple[str, str], ...] = ()
    """(可選值, 顯示名稱)。"""
    item_url: str = ""
    ignore_when: tuple[tuple[str, str], ...] = ()
    """(別的欄位, 那個欄位的值)。成立時這一欄就不問。"""
    required: bool = False
    human_only: bool = False
    follow_convention: bool = False
    original_key: str | None = None

    def as_declaration(self) -> dict[str, Any]:
        declaration: dict[str, Any] = {
            "title": self.title or self.key,
            "x-prompt": self.prompt,
            "x-input": self.input,
        }
        if self.input == "integer-list":
            declaration["type"] = "array"
            declaration["items"] = {"type": "integer"}
        else:
            declaration["type"] = "string"
        if self.choices:
            declaration["enum"] = [value for value, _ in self.choices]
            declaration["x-choice-labels"] = {value: label for value, label in self.choices}
        if self.item_url:
            declaration["x-item-url"] = self.item_url
        if self.ignore_when:
            declaration["x-ignore-when"] = dict(self.ignore_when)
        if self.human_only:
            declaration["x-human-only"] = True
        if self.follow_convention:
            declaration["x-follow-convention"] = True
        return declaration


def draft_of(key: str, declaration: Mapping[str, Any], required: bool) -> FieldDraft:
    labels = declaration.get("x-choice-labels", {})
    return FieldDraft(
        key=key,
        title=declaration.get("title", key),
        prompt=declaration.get("x-prompt", ""),
        input=declaration.get("x-input", "text"),
        choices=tuple(
            (value, labels.get(value, value)) for value in declaration.get("enum", ())
        ),
        item_url=declaration.get("x-item-url", ""),
        ignore_when=tuple(
            (name, str(value)) for name, value in declaration.get("x-ignore-when", {}).items()
        ),
        required=required,
        human_only=bool(declaration.get("x-human-only", False)),
        follow_convention=bool(declaration.get("x-follow-convention", False)),
        original_key=key,
    )


def spell_pairs(pairs: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{left}={right}" for left, right in pairs)


def read_pairs(raw: str, *, label_optional: bool) -> tuple[tuple[str, str], ...]:
    """`a=1, b=2` 讀成成對的東西。

    label_optional 是給可選值用的：只寫 `feat` 就以值本身當顯示名稱，因為英文專案
    的標籤本來就等於值，不該逼人多打一次。
    """
    collected: list[tuple[str, str]] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        left, separator, right = piece.partition("=")
        left, right = left.strip(), right.strip()
        if not left:
            raise ValueError(f"「{piece}」左邊是空的。")
        if not separator or not right:
            if not label_optional:
                raise ValueError(f"「{piece}」要寫成 欄位=值。")
            right = left
        collected.append((left, right))
    return tuple(collected)

def apply_plan(plan: FieldPlan, controller: Any) -> tuple[str, ...]:
    """把計畫落地，回傳被改寫的那幾筆備註。

    順序不能反：宣告先落地的話，中間那一刻宣告已經換了、備註還是舊的，這時候任何一次
    讀取都會整批驗證失敗——那正是這條路要避免的事。
    """
    rewritten: list[str] = []
    for old_key, new_key in plan.renames:
        rewritten.extend(controller.rename_field(old_key, new_key))
    for key in plan.drops:
        rewritten.extend(controller.drop_field(key))

    schema.save_schema(plan.document)
    return tuple(rewritten)
