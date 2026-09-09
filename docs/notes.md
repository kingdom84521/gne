# 備註本身

> 一筆備註從哪裡開始、誰寫的、怎麼跟 remote 同步　｜　回到 [readme](../readme.md)

## 新備註從哪裡開始

`.gne/default-note` 是 repo 對「一筆備註還沒填之前長什麼樣」的宣告，與欄位宣告放在同一個
目錄底下。`Ctrl+D` 在畫面上改，或直接寫檔——格式與備註本身一樣是 YAML：

```yaml
type: skip
```

commit 標題說得出種類時以標題為準（`fix:` 開頭就是 fix），說不出來時才用這個檔案，
兩者都沒有才落到 `skip`。它是「起點」而不是「一筆備註」，所以不必把必填欄位填滿；
但欄位名與值仍要符合宣告檔，寫錯會在讀取時就被擋下來。

問句會直接說出直接 Enter 會得到什麼：新備註寫「用預設」，已經有備註的寫「保留」。
不想逐題按過去就用 `a`／`A`，那條路不進問答。

## AI 產生的備註

AI 代填的備註帶一個 `ai_generated` 欄位：

```yaml
type: fix
change_log: 修正…
ai_generated: true
```

它只回答一個問題：這一筆是不是 AI 寫的。哪幾欄由誰填不記——審閱是逐筆看整份備註，
不是逐欄核對。讀的時候看真值而不是看鍵在不在，所以 `ai_generated: false` 也表達得出
「不是 AI 寫的」。

這個欄位刻意**不在** `note-schema.json` 裡——它記的不是 release note 的內容，而是這份備註
是誰寫的。輸出 release note 的每一條路徑（純文字、xlsx）都無視它，只有審閱那一條讀它。
名字打錯就會被 `additionalProperties: false` 當成未宣告的欄位擋下。

審閱就是把工具打開，只是這次只想看 AI 填的那些——所以它是一個旗標，不是另一套介面：

```sh
gne --ai-generated                       # 我的 commit ∩ AI 填的；儲存這一筆就是確認
gne list --filter ai-generated           # 不進畫面的檢視，可接管線
```

`--ai-generated` 是在既有的作者篩選之上再收一次，所以預設看到的是「自己的」且「AI 填的」；
要看別人的加 `--all-authors`。

人工寫入本身就是確認：TUI 的表單依欄位重建整份備註，`gne note set` 沒帶 `--ai-generated` 就是人在寫，
記號在那一刻消失，不必另外下指令清除。

最後一道防線是 [.githooks/pre-push](../.githooks/pre-push)：帶著記號的備註推不上 remote。
要它生效，在被標註的那個 repo 裡把 hook 路徑指過去（`git config core.hooksPath .githooks`）。

## 與 remote 的同步

跟哪個 remote 同步：`git config gne.remote <name>` 指定；沒設就用 `origin`，沒有 `origin`
但只有一個 remote 就用那一個。**一個 remote 都沒有也完全能用**——備註寫在本機，
`gne note push` 會說沒有可以推的對象，其餘一切照常。remote 存在但連不上（VPN 沒開、機器關著）
時取回失敗只是一則說明，不會擋住你把手上這幾筆填完；推送則仍然會失敗，因為那件事真的沒做到。

取回走的是 git 對分支的那一套：remote 的備註取到 `refs/notes/origin/commits`（remote-tracking
ref），本機那一份不會被它蓋掉，所以**本機有還沒推的備註也一樣取得回來**。取回之後：

| 狀態 | gne 做什麼 |
| --- | --- |
| 本機落後 | 直接快轉——取回本來就是這個意思 |
| 本機領先 | 什麼都不做，也不囉嗦 |
| 兩邊都有獨有的 | 不動本機那一份，告訴你兩個數字與 `git notes merge origin/commits` |
| 沒有 remote | 什麼都不做 |
| remote 連不上 | 說一聲，繼續讓你填 |

合併備註可能衝突，那是人要決定的事，不是取回順手做掉的事。

`refs/notes` 是單一個 ref，所以任何一次推送都會把本機所有備註送上 remote，包含還沒確認的那些。
記號跟著備註走，別人 `gne --ai-generated` 一樣看得到，所以這不會弄丟資訊——但要「確認完才公開」就得
在填寫時一路 `--no-push`，等審閱完再 `gne note push`。
