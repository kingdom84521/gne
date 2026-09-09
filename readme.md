# gne — git note editor

在 commit 上掛 release note 用的工具。備註以 YAML 存在 `refs/notes/commits`，要記哪些欄位
由**你的 repo** 說——宣告檔在 `.gne/note-schema.json`，gne 自己不帶預設欄位。

一個畫面把「這一段有哪些 commit、哪些還沒填、這一筆該填什麼」放在一起；同樣的每一件事都有
不進畫面的子命令，給腳本與 AI 走。

```
變更種類: fix（錯誤）
變更說明? （Enter 留空）
▌
```

## 一分鐘上手

```sh
gne schema init         # 問出這個 repo 要記哪些欄位（第一次才要）
gne v1.2.0...HEAD       # 開編輯器，列出這個區間裡自己還沒填的 commit
gne                     # 同上，沿用上一次用過的區間
gne list --format json  # 不進畫面，把資料倒出來
gne export              # 匯出 xlsx
```

畫面上：`↑` `↓` 換 commit、`Enter` 進問答、`a`／`Shift+A` 用預設內容填、`s` 一次寫入並推送、
`Esc` 退一層、`Ctrl+H` 列出全部按鍵。詳細的一份在 [docs/editor.md](docs/editor.md)。

## 安裝

```sh
./install_dev_env.sh          # 建 .venv，以 editable 模式裝進去
```

或裝進現成的環境：`pip install -e ".[test]"`。裝完就有 `gne` 指令，相依來自
[pyproject.toml](pyproject.toml)。

接著在要標註的那個 repo 裡跑一次 `gne schema init`。它不塞一份現成的欄位給你——開一個空的
欄位一覽問你要記什麼，用的是跟畫面上 `Ctrl+F` 一樣的表單。寫出來的 `.gne/note-schema.json`
要 commit：欄位是整個專案共用的約定。

## 五個入口

| 命令 | 用途 |
| --- | --- |
| `gne [<區間>\|<hash>]` | 開編輯器。沒有子命令名字，因為那是這個工具平常在做的事 |
| `gne list` | 用文字列出區間內的 commit 與備註，`--format json` 可接管線 |
| `gne export` | 匯出 xlsx，不管填到什麼程度 |
| `gne note …` | 逐條讀寫備註：`show` `set` `remove` `prune` `backup` `push` |
| `gne schema …` | 欄位宣告：`show` `init` `order` `add` `edit` `remove` |

**`gne note` 與 `gne schema` 是畫面的另一條路**：人在畫面上做得到的每一件事，這裡都有一條
指令做得到，不進畫面、可接管線。給腳本與 AI 走的就是這一條。全部選項見
[docs/cli.md](docs/cli.md)。

## 文件

| | |
| --- | --- |
| [docs/editor.md](docs/editor.md) | 編輯器：畫面怎麼排、一問一答怎麼運作、完整按鍵表 |
| [docs/cli.md](docs/cli.md) | 五個入口的完整選項，以及「要看哪一段」怎麼決定 |
| [docs/schema.md](docs/schema.md) | 欄位宣告：`x-*` 關鍵字、增修欄位、改名與刪除的遷移 |
| [docs/notes.md](docs/notes.md) | 備註本身：新備註的起點、AI 產生的記號、與 remote 的同步 |
| [docs/advisor.md](docs/advisor.md) | AI 建議：`GNE_ADVISOR` 的契約 |
| [docs/development.md](docs/development.md) | 專案結構、分層界線、怎麼跑測試 |

## 環境變數

| | 作用 |
| --- | --- |
| `GNE_SCHEMA` | 欄位宣告的路徑，蓋掉 repo 的 `.gne/note-schema.json` |
| `GNE_ADVISOR` | 問 AI 的那一支指令，就像 `GIT_EDITOR` 指定編輯器 |
| `GNE_FROM` / `GNE_TO` | 區間的兩端；設一次，之後 `gne` 不帶任何東西也會動 |

跟哪個 remote 同步由 `git config gne.remote` 決定，沒設就用 `origin`。全域 `--no-push` 讓異動
不推送，批次填寫時建議加上，收尾再 `gne note push` 推一次。
