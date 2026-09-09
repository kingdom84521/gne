# 開發

> 專案結構、分層界線、怎麼跑測試　｜　回到 [readme](../readme.md)

## 專案結構

```
gne/
  pyproject.toml        套件宣告、pytest 設定、分層 contract
  src/gne/
    cli.py              命令列入口
    tui/                互動編輯器（Textual）
    render.py           note → 文字 / YAML / JSON
    export.py           note → xlsx
    core/               欄位宣告、備註讀寫、git 存取
      note-schema.json  範例，給人看 x-* 怎麼寫；生效的那一份在被標註的 repo 的 .gne/ 底下
      schema.py  provenance.py  entity.py  git.py  types.py
  tests/
```

界線只有一個方向：上面可以叫下面，下面不能回頭。`core` 不認識 textual、argparse 與
openpyxl，所以換掉介面不必動核心。這條界線是機器在檢查，不是靠資料夾名字提醒——
規則寫在 [pyproject.toml](../pyproject.toml) 的 import-linter contract 裡：

```sh
PYTHONPATH=src lint-imports   # 2 kept, 0 broken
```

（`lint-imports` 不讀 pytest 的 `pythonpath`，所以 `src` 要自己給；裝成 editable
（`pip install -e .`）之後可以省。）

新增一個頂層模組而 contract 沒跟著改，`tests/test_packaging.py` 會失敗，不會靜靜地
漏掉那一層。

## 測試與檢查

```sh
python3 -m pytest
PYTHONPATH=src lint-imports
```
