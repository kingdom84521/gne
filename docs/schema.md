# 欄位宣告

> 要記哪些欄位由你的 repo 說：`x-*` 關鍵字、增修欄位、改名與刪除的遷移　｜　回到 [readme](../readme.md)

## 第一次：問出欄位

在要標註的那個 repo 裡跑一次 `gne schema init`。它不塞一份現成的欄位給你——開一個空的
欄位一覽問你要記什麼，用的是跟畫面上 `Ctrl+F` 一樣的表單：

```
  欄位宣告

  這個專案的 release note 要記哪些欄位？按 a 一欄一欄加，加完 ctrl+s
  寫入。
  之後要改，用 gne 裡的 ctrl+f，同一張表單。

  ┌──────────────────────────────────────────────────────────┐
  └──────────────────────────────────────────────────────────┘

  a 新增 ｜ e 修改 ｜ d 刪除 ｜ ctrl+s 儲存；Esc 關閉，或點對話框外面
```

寫出來的 `.gne/note-schema.json` 要 commit——欄位是整個專案共用的約定。
`src/gne/core/note-schema.json` 是一個看得到 `x-*` 怎麼寫的例子，gne 自己不讀它。

## 之後：改欄位

`Ctrl+F` 在畫面上改，或直接改 `.gne/note-schema.json`（`GNE_SCHEMA` 可以指到別的路徑，
就像 `GNE_ADVISOR` 指定顧問）。兩條路寫的是同一個檔。驗證規則、編輯器表單、`gne note set` 的旗標、
文字與 JSON 輸出、xlsx 表頭都由它衍生，`properties` 的出現順序就是顯示順序。

**改欄位名或刪欄位不只是改宣告。** 宣告的 `additionalProperties` 是 `false`，既有備註裡
那個欄位沒跟著改，下一次讀取就整批驗證失敗。所以畫面上改的時候，gne 會先說有幾筆備註帶著
這個欄位、要一起改寫，答應了才動手——備註先改完，宣告才落地。

改寫的對象必須是完整的那一份，所以動手之前會先跟 remote 併成**兩邊的聯集**：remote 有而
本機沒有的備註先併進來，再一起改。併不起來——同一個 commit 兩邊各寫了不同的東西——就
**拒絕整個異動**，什麼都不動。合併要挑一邊，挑哪一邊是人的決定，不是欄位改名順手做掉的事：

```
本機與 remote 對同一個 commit 各寫了不同的備註：有 2 筆對不起來，
先 git notes merge origin/commits 決定要留哪一份，再改欄位
```

- `x-input`：`text` / `multiline` / `integer-list` / `choice`，決定值怎麼解析（`integer-list` 收逗號分隔的數字，`choice` 把可選值印在問題裡）。
- `x-prompt`：**必填**，這個欄位該怎麼填。人在 `gne schema show` 讀它，顧問收到的 `fields`
  裡也是同一份，填寫規則因此只有一處。沒有它的欄位沒人填得出來，所以宣告時漏了會當場報錯。
- `x-choice-labels`：`choice` 欄位的中文標籤。
- `x-item-url`：`integer-list` 每一項要展開成的網址。
- `x-human-only`：這個欄位只能由人填。AI 寫入時碰到它會被擋下來，不是靠 `x-prompt` 拜託。
- `x-ignore-when`：別的欄位變成什麼值時，這一欄就不必問了。
- `x-follow-convention`：commit 前綴對得上可選值時就用它（只有 `choice` 欄位用得上）。

不進畫面也做得到同樣的事，旗標與表單一一對應：

```sh
gne schema add impact --title 影響 --prompt "影響有多大。" \
  --input choice --choices "big=很大,small=不大" --ignore-when "type=skip"

gne schema edit impact --title 衝擊          # 沒給的旗標保持原樣
gne schema edit change_log --rename summary  # 備註跟著改名
gne schema remove change_log                 # 先說會影響幾筆
gne schema remove change_log --apply --yes   # 真的刪
```

順序就是 `properties` 的順序，要重排用 `gne schema order`——列出現有的每一個欄位，剛好一次：

```sh
gne schema order                                          # 現在的順序
gne schema order type change_log redmine_ids spec_change  # 排成這樣
```

漏掉的欄位不是「排在後面」而是會消失，所以部分清單會被擋下來。

`Ctrl+F` 的表單收得下上面每一個關鍵字：成對的東西（可選值對標籤、欄位對值）寫成
`feat=功能, fix=錯誤` 與 `type=skip`，一格搞定。所以**畫面上做得到的事不比改檔案少**——
`tests/test_tui_settings.py` 拿隨附的範本逐欄對過去，表單少收一個關鍵字那一條就會紅。
