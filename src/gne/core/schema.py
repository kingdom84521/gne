"""載入欄位宣告，並衍生出各處需要的對照表。

宣告檔屬於被標註的那個 repo，不屬於 gne：release note 要記哪些欄位是專案自己的事，
一個工具沒有立場替所有人決定。所以它放在 repo 的 .gne/ 底下，套件裡那一份只是
gne init 用的範本。

欄位的唯一來源是宣告檔。標準 JSON Schema 關鍵字由 jsonschema 驗證，
x-* 擴充關鍵字由 pydantic 驗證——JSON Schema 規格要求驗證器忽略未知關鍵字，
擴充區塊的錯字因此不會被 jsonschema 攔下，必須另外把關。
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import git
from .types import NoteDocument

SCHEMA_ENV = "GNE_SCHEMA"
SCHEMA_RELATIVE = Path(".gne/note-schema.json")
TEMPLATE_PATH = Path(__file__).resolve().parent / "note-schema.json"

type InputKind = Literal["text", "multiline", "integer-list", "choice"]


class NoteValidationError(ValueError):
    """note 文件不符合欄位宣告。"""

    def __init__(self, violations: Sequence[str]):
        self.violations = list(violations)
        super().__init__("；".join(self.violations))


class SchemaDeclarationError(ValueError):
    """宣告檔本身寫錯了。"""


class SchemaNotDeclared(FileNotFoundError):
    """這個 repo 還沒有欄位宣告。"""


class FieldInputError(ValueError):
    """使用者為某個欄位輸入了這個欄位接受不了的內容。"""

    def __init__(self, field_key: str, message: str):
        self.field_key = field_key
        super().__init__(message)


class FieldExtension(BaseModel):
    """一個欄位宣告裡的 x-* 區塊。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: InputKind = Field(alias="x-input")
    prompt: str = Field(alias="x-prompt")
    choice_labels: dict[str, str] = Field(default_factory=dict, alias="x-choice-labels")
    item_url: str | None = Field(default=None, alias="x-item-url")
    human_only: bool = Field(default=False, alias="x-human-only")
    ignore_when: dict[str, Any] = Field(default_factory=dict, alias="x-ignore-when")
    follow_convention: bool = Field(default=False, alias="x-follow-convention")

    @model_validator(mode="after")
    def _check_input_coherence(self) -> "FieldExtension":
        if not self.prompt.strip():
            raise ValueError("x-prompt 不能是空的——沒有填寫指示的欄位沒人填得出來")
        if self.input == "choice" and not self.choice_labels:
            raise ValueError('x-input 為 "choice" 時必須提供 x-choice-labels')
        if self.input != "choice" and self.choice_labels:
            raise ValueError('x-choice-labels 只能用在 x-input 為 "choice" 的欄位')
        if self.item_url is not None and self.input != "integer-list":
            raise ValueError('x-item-url 只能用在 x-input 為 "integer-list" 的欄位')
        if self.follow_convention and self.input != "choice":
            raise ValueError('x-follow-convention 只能用在 x-input 為 "choice" 的欄位——'
                             "前綴要對得上的正是那組可選值")
        return self


class NoteField(BaseModel):
    """從宣告檔衍生出來的單一欄位規格。"""

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    prompt: str
    required: bool
    input: InputKind
    choices: tuple[str, ...] = ()
    choice_labels: Mapping[str, str] = {}
    item_url: str | None = None
    human_only: bool = False
    ignore_when: Mapping[str, Any] = {}
    """其他欄位變成這些值時，這一欄就不必問了。空的代表永遠要問。"""

    follow_convention: bool = False
    """commit 標題的前綴對得上可選值時，就拿它當這一欄的預設值。"""

    @property
    def cli_flag(self) -> str:
        return "--" + self.key.replace("_", "-")

    def label_of(self, value: str) -> str:
        return self.choice_labels.get(value, value)

    def format_item(self, value: object) -> str:
        return self.item_url.format(value=value) if self.item_url else str(value)


def read_schema(path: Path) -> Mapping[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def schema_path() -> Path:
    """這個 repo 的欄位宣告在哪。

    `GNE_SCHEMA` 指定路徑，就像 `GNE_ADVISOR` 指定顧問；沒設就找 repo 的
    .gne/note-schema.json。套件裡的範本不當預設值——真的拿它當預設，等於讓每個人的
    release note 都長成別人專案的樣子。
    """
    override = os.environ.get(SCHEMA_ENV, "").strip()
    if override:
        return Path(override)
    return git.repo_root() / SCHEMA_RELATIVE


@cache
def load_schema() -> Mapping[str, Any]:
    path = schema_path()
    try:
        return read_schema(path)
    except FileNotFoundError as error:
        raise SchemaNotDeclared(
            f"找不到欄位宣告 {path}。\n"
            "跑 gne init 從範本建一份，或用 GNE_SCHEMA 指到既有的那一份。"
        ) from error
    except json.JSONDecodeError as error:
        raise SchemaDeclarationError(f"{path} 不是合法的 JSON：{error}") from error
    except SchemaError as error:
        raise SchemaDeclarationError(f"{path} 不是合法的 JSON Schema：{error.message}") from error


def build_fields(document: Mapping[str, Any]) -> tuple[NoteField, ...]:
    required = set(document.get("required", ()))
    fields: list[NoteField] = []

    for key, declaration in document["properties"].items():
        extension_keywords = {
            keyword: value
            for keyword, value in declaration.items()
            if keyword.startswith("x-")
        }
        try:
            extension = FieldExtension.model_validate(extension_keywords)
        except ValueError as error:
            raise SchemaDeclarationError(f"欄位 {key} 的擴充關鍵字有誤：{error}") from error

        unknown_conditions = [
            key for key in extension.ignore_when if key not in document["properties"]
        ]
        if unknown_conditions:
            raise SchemaDeclarationError(
                f"欄位 {key} 的 x-ignore-when 提到宣告檔沒有的欄位：{unknown_conditions}"
            )

        choices = tuple(declaration.get("enum", ()))
        if extension.input == "choice":
            if not choices:
                raise SchemaDeclarationError(f"欄位 {key} 的 x-input 為 choice，但沒有宣告 enum")
            missing = [choice for choice in choices if choice not in extension.choice_labels]
            if missing:
                raise SchemaDeclarationError(
                    f"欄位 {key} 的 x-choice-labels 缺少 enum 值的標籤：{missing}"
                )
            unknown = [value for value in extension.choice_labels if value not in choices]
            if unknown:
                raise SchemaDeclarationError(
                    f"欄位 {key} 的 x-choice-labels 有 enum 裡沒有的值：{unknown}"
                )

        fields.append(
            NoteField(
                key=key,
                title=declaration.get("title", key),
                prompt=extension.prompt,
                required=key in required,
                input=extension.input,
                choices=choices,
                choice_labels=extension.choice_labels,
                item_url=extension.item_url,
                human_only=extension.human_only,
                ignore_when=extension.ignore_when,
                follow_convention=extension.follow_convention,
            )
        )

    return tuple(fields)


@cache
def note_fields() -> tuple[NoteField, ...]:
    return build_fields(load_schema())


@cache
def field_by_key() -> Mapping[str, NoteField]:
    return {field.key: field for field in note_fields()}


@cache
def _note_validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


@cache
def _partial_validator() -> Draft202012Validator:
    """驗證一份還沒填完的內容：欄位名與值都要對，但不要求必填欄位到齊。

    預設值與 AI 的建議都是「起點」而不是「一筆備註」——拿完整備註的規則去驗它們，
    等於要求起點就得是終點。必填的把關留在寫入那一刻（validate_note）。
    """
    declaration = {key: value for key, value in load_schema().items() if key != "required"}
    return Draft202012Validator(declaration)


def _violations(validator: Draft202012Validator, document: NoteDocument) -> list[str]:
    return [
        f"{'/'.join(str(part) for part in error.path) or '(根層級)'}：{error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    ]


def validate_partial(document: NoteDocument) -> None:
    violations = _violations(_partial_validator(), document)
    if violations:
        raise NoteValidationError(violations)


def validate_note(document: NoteDocument) -> None:
    violations = _violations(_note_validator(), document)
    if violations:
        raise NoteValidationError(violations)


def ignored(field: NoteField, note: NoteDocument) -> bool:
    """依目前填到的內容，這一欄還需要問嗎。

    條件是「哪個欄位等於什麼值」，不是一種運算式語言——宣告檔要看得懂，而目前需要
    表達的就只有「種類是 skip 時其餘欄位不必填」這一件事。
    """
    return bool(field.ignore_when) and all(
        note.get(key) == value for key, value in field.ignore_when.items()
    )


def from_convention(subject: str) -> str:
    """commit 標題的 convention 前綴。`fix(i18n): …` 與 `fix: …` 都是 fix。"""
    head = subject.split(":")[0].strip() if ":" in subject else ""
    return re.sub(r"\(.*\)$", "", head).strip()


def ignore_reason(field: NoteField) -> str:
    known = field_by_key()
    return "、".join(
        f"{known[key].title if key in known else key} 是 {value}"
        for key, value in field.ignore_when.items()
    )


def is_empty(value: object) -> bool:
    """依 note 的語意判斷一個欄位值是否為空。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def is_blank_note(document: NoteDocument) -> bool:
    """每個宣告過的欄位都空，且沒有宣告以外的內容——這種 note 不帶任何資訊。"""
    declared = {field.key for field in note_fields()}
    if any(key not in declared for key in document):
        return False
    return all(is_empty(document.get(field.key)) for field in note_fields())


def strip_empty(document: NoteDocument) -> dict[str, Any]:
    return {key: value for key, value in document.items() if not is_empty(value)}


def parse_value(field: NoteField, raw: str) -> str | list[int]:
    """把使用者鍵入的字串轉成欄位的值。CLI 旗標與 TUI 問答共用這一份規則。"""
    if field.choices and raw and raw not in field.choices:
        raise FieldInputError(
            field.key, f"{field.title}只接受 {' / '.join(field.choices)}，讀到「{raw}」。"
        )
    if field.input != "integer-list":
        return raw
    items = [piece.strip() for piece in raw.split(",") if piece.strip()]
    for item in items:
        if not item.isdigit():
            raise FieldInputError(
                field.key, f"{field.title}只接受以逗號分隔的數字，讀到「{item}」。"
            )
    return [int(item) for item in items]


def format_value(field: NoteField, value: object) -> str:
    """parse_value 的反向：把欄位的值變回可以編輯的字串。"""
    if is_empty(value):
        return ""
    if field.input == "integer-list":
        return ", ".join(str(item) for item in value)
    return str(value)
