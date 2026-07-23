# PAD だけでバッチ実行する（ブラウザ拡張機能なし・WebDriver を HTTP で操作）

Power Automate Desktop（PAD）の Web 自動化アクションは専用のブラウザ拡張機能を必要とするが、
**WebDriver は拡張機能とは無関係**で、`msedgedriver.exe` 自体がローカルの HTTP サーバーとして動く。
つまり **HTTP リクエストを送れれば、拡張機能なしでブラウザを完全に操作できる**。
PAD の「Web サービスの呼び出し」がまさにそれに当たる。

このドキュメントは、`run_batch.py`（Python 版バッチランナー）と同じことを、
**Python を使わず PAD だけで**実現するための組み立て手順である。

---

## 🧭 全体像

| 役割 | 担当 |
|---|---|
| 明細（Excel/CSV）の読み込み、件数ループ、skip 判定、進捗、結果 CSV、リトライ | **PAD の標準アクション** |
| ブラウザの起動・画面遷移・クリック・入力・スクショ | **WebDriver**（PAD から HTTP で指示） |

Python 版との対応:

| Python 版 (`run_batch.py`) | PAD 版 |
|---|---|
| `--details` の CSV/xlsx 読み込み | 「CSV ファイルから読み取る」 |
| 明細ごとのループ | 「For each」 |
| `skip` 列 | 「If」 |
| `setup` / `loop` / `recover` | サブフロー 3 つに分ける |
| 失敗しても次の件へ | 「エラー発生時（On block error）」 |
| 進捗表示 | 「テキストをファイルに書き込む」／通知 |
| 結果 CSV | 「CSV ファイルに書き込む」 |
| エビデンスのスクショ | PAD の「スクリーンショットを取得」 |

---

## 🛠️ 事前準備

1. **msedgedriver.exe** を用意する（Edge のバージョンと**必ず一致**させる。Edge が更新されたら入れ替える）。
2. PAD の最初に「**アプリケーションの実行**」で次を起動する。
   - アプリケーション: `C:\path\to\msedgedriver.exe`
   - 引数: `--port=9515`
   - ウィンドウ スタイル: 非表示 / 実行後: **待たない**
3. **プロキシ除外**: 社内プロキシがあると `localhost` 宛が失敗することがある。
   Windows のプロキシ設定で `localhost;127.0.0.1` を除外に入れておく
   （Ollama で `NO_PROXY=localhost` を設定したのと同じ対策）。
4. 終了時に `taskkill /IM msedgedriver.exe /F` を実行するフローを入れておくと、プロセスが残らない。

---

## 🤖 Robin コードを自動生成して貼り付ける（推奨）

PAD のフローは内部的に **Robin 言語**で表現されており、フローデザイナーのキャンバスに
**Robin のテキストを貼り付ける（Ctrl+V）とアクションが並ぶ**。つまり、上のアクションを 1 つずつ
手で置く代わりに、**生成したコードを貼り付けるだけ**でフローを組める。

```powershell
# 自宅の Python 環境で生成（ブラウザも WebDriver も不要）
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json `
    --details "C:\PAD\edi2_batch.csv" --id-column "プロジェクト番号" `
    --robin output/pad_flow.robin.txt `
    --driver-exe "C:\WebDriver\msedgedriver.exe" --pad-out-dir "C:\PAD\output"
```

生成される内容:

- 設定変数（ドライバのパス／URL／明細 CSV／出力先／資格情報の参照）
- **共通 JavaScript は別ファイル**（`pad_flow.jsact.js`）として同時生成され、フローからは
  「ファイルからテキストを読み取る」で `%JsAct%` に読み込む
- WebDriver 起動 → セッション開始 → `SessionId` の取り出し
- **セットアップ**（ログイン〜開始画面）の Web サービス呼び出し一式
- 明細 CSV の読み込み → **`LOOP FOREACH`** → skip 判定 → 1 件分の操作 → エビデンス →
  失敗時は結果 CSV に記録して次の件へ
- 後片付け（セッション削除・ドライバ終了・結果の表示）

### 📌 貼り付けの制約（実機で判明）

PAD は貼り付けたテキストを解釈できないと**エラーも出さず黙って無視する**。実機での切り分けの結果、
制約は次のとおりだった（PAD 無料版・Windows 11 で確認）。

| 内容 | 結果 |
|---|---|
| 記号なしの短い文字列 | ○ |
| 波かっこ `{ }` を含む | ○ |
| **単引用符 `'` を含む** | **× 無視される** |
| 角かっこ `[ ]`・比較演算子 | ○ |
| JSON 形式（`{"a": ["b"]}`） | ○ |
| 約 300 文字 / 約 700 文字 | ○ |

つまり**長さは問題ではなく、`$'''…'''` の中身のエスケープが原因**だった。実機で確定した規則は次の 2 つ。

| 文字 | 書き方 | 理由 |
|---|---|---|
| 単引用符 `'` | `\'` にエスケープ（または使わない） | 生のままだと貼り付けが無視される |
| バックスラッシュ `\` | **`\\` に二重化** | `\%` が「エスケープされた %」と解釈され、変数展開の `%` が対応せず失敗する |

たとえば `$'''%OutDir%\%ShotName%.png'''` は貼り付けできず、`$'''%OutDir%\\%ShotName%.png'''` なら通る。
そのため生成コードは次のように単引用符を避けている。

- **JavaScript の文字列はバッククォート** `` `…` `` で書く（`'` も `"` も使わない）。
  実行時に単引用符が必要な箇所は `String.fromCharCode(39)` で作る。
- **`{{列名}}` は `%Row['列名']%` にしない。** ループ先頭で `SET Col1 TO Row['発注番号']` のように
  変数へ取り出し、リテラル内では `%Col1%` を使う（`SET` 行の `'` はリテラルの外なので問題ない）。
- **`xpath///*[@id="X"]` は `id/X` に変換**する（JS 側が `document.getElementById` で解決する）。
  引用符が残る候補は生成時に除外される。

### 📌 それでも貼り付けがうまくいかないとき

PAD は貼り付けたテキストを解釈できないと**エラーも出さず黙って無視する**。経験上の対処:

- **長すぎる 1 行は貼れない。** 共通 JavaScript（約 1,700 文字）を `SET` で直接貼ろうとすると無視される。
  そのため生成物では **`.js` ファイルに逃がして読み込む**方式にしてある。
  生成された `pad_flow.jsact.js` を、PAD 実行 PC の出力フォルダ（既定 `C:\PAD\output`）に置くこと。
- **どうしても読み込みアクションが通らない場合**は、「変数の設定」アクションを手で 1 つ置き、
  値の欄に `.js` の中身を直接貼り付ける（UI の入力欄なら長い文字列でも入る）。
  変数名は `JsAct` にする。
- **一括貼り付けが無視される場合は分割する。** 「設定〜セッション開始まで」「セットアップ」
  「ループ」「後片付け」の 4 ブロックに分けて貼ると、どこで弾かれているか特定しやすい。
- 1 行だけ弾かれている場合、その行のアクション名が PAD のバージョンと違う可能性が高い。
  PAD で同じアクションを 1 つ置いてコピー（Ctrl+C）し、正しい書式に置き換える。

`{{列名}}` は **`%Row['列名']%`** に自動変換されるので、明細の値がそのまま流し込まれる
（`aria/{{発注番号}}` のようなセレクタ内の指定も変換される）。
`{{SECRET:…}}` は **`%EdiUser%` / `%EdiPassword%`** への参照に置き換わるため、
生成物に資格情報の平文は入らない。PAD 側で「資格情報」または暗号化変数を割り当てること。

### ✅ 実機で確認できたアクション書式（PAD 無料版 / Windows 11）

貼り付けが通ることを確認済み:

| 用途 | Robin |
|---|---|
| WebDriver 起動 | `System.RunApplication.RunApplication` |
| HTTP 呼び出し | `Web.InvokeWebService.InvokeWebService` |
| JSON 解析 | `Variables.ConvertJsonToCustomObject` |
| CSV 読み込み | `File.ReadCsvFile.ReadCsvFile` |
| テキスト追記 | `File.WriteText` |
| 現在日時 | `DateTime.GetCurrentDateTime.Local` |
| **スクリーンショット** | **`Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile`**（`File:` と `ImageFormat: System.ImageFormat.Png`） |
| ループ / 条件 / 変数 | `LOOP FOREACH` / `IF` / `SET` |

> **⚠️ ファイル名に日時を入れるときの注意**
> `DateTime.DateTimeFormat.DateAndTime` は `2026/07/23 8:41:00` のような値を返し、`/` と `:` は
> Windows のファイル名に使えない。`Text.ConvertDateTimeToText` で `yyyyMMdd_HHmmss` に整形してから使う。
> また出力フォルダの変数（`OutDir`）末尾に `\` を付けないこと（パスが二重区切りになる）。

> **貼り付け後に必ず確認する点**
> `※要確認` と書かれた行（ドライバ起動・CSV 読み込み・スクリーンショット・プロセス終了）は、
> PAD のバージョンによってアクション名や引数が異なることがある。
> PAD で同じアクションを 1 つキャンバスに置き、それを選択してコピー（Ctrl+C）してテキストに貼ると
> **その環境での正しい書式**が分かるので、差分があれば置き換える。

---

## 🔌 使う HTTP 呼び出しは 5 種類だけ

PAD の「Web サービスの呼び出し」で、**メソッド `POST`／`GET`／`DELETE`**、
**コンテンツタイプ `application/json`**、本文は下表の JSON を指定する。
応答は「**JSON をカスタム オブジェクトに変換**」で解析する。

| 目的 | メソッド | URL | 本文 |
|---|---|---|---|
| ① セッション開始（ブラウザ起動） | POST | `http://127.0.0.1:9515/session` | `{"capabilities":{"alwaysMatch":{"browserName":"MicrosoftEdge"}}}` |
| ② ウィンドウサイズ | POST | `…/session/%SessionId%/window/rect` | `{"width":1400,"height":900}` |
| ③ ページを開く | POST | `…/session/%SessionId%/url` | `{"url":"https://…"}` |
| ④ **クリック／入力（共通）** | POST | `…/session/%SessionId%/execute/sync` | `{"script":%JsAct%,"args":[ [セレクタ候補], "click" か "fill", "値" ]}` |
| ⑤ セッション終了 | DELETE | `…/session/%SessionId%` | （なし） |

① の応答 `{"value":{"sessionId":"…"}}` から `sessionId` を取り出し、変数 `%SessionId%` に入れて以降で使う。

> **要素の操作を ④ に一本化するのがコツ。**
> W3C 標準の「要素を検索して要素 ID を得る → その ID を操作する」方式は往復が増え、
> `element-6066-11e4-a52e-4f735466cecf` という長いキーの取り回しが PAD では煩雑になる。
> ④ の JavaScript 方式なら、**PAD 側は同じ形のアクション 1 種類**を用意し、`args` だけ差し替えればよい。

---

## 📜 共通 JavaScript（変数 `%JsAct%` に入れておく）

フローの最初に「**変数の設定**」で、この JavaScript を丸ごと 1 つのテキスト変数に入れる。
以後、④ の呼び出しではこの変数を使い回す（毎回書かない）。

```javascript
var cands = arguments[0], action = arguments[1], value = arguments[2];
var Q = String.fromCharCode(39), DQ = String.fromCharCode(34);
function lit(s) { if (s.indexOf(Q) < 0) { return Q + s + Q; } return DQ + s + DQ; }
function byXPath(xp) {
  try { return document.evaluate(xp, document, null, 9, null).singleNodeValue; }
  catch (e) { return null; }
}
function find(sel) {
  try {
    if (sel.indexOf(`id/`) === 0) { return document.getElementById(sel.slice(3)); }
    if (sel.indexOf(`xpath/`) === 0) { return byXPath(sel.slice(6)); }
    if (sel.indexOf(`text/`) === 0) {
      var t = sel.slice(5).trim();
      return byXPath(`//*[not(self::script) and normalize-space(text())=` + lit(t) + `]`);
    }
    if (sel.indexOf(`aria/`) === 0) {
      var n = sel.slice(5).split(`[`)[0].trim();
      var el = document.querySelector(`[aria-label=` + lit(n) + `]`);
      if (el) { return el; }
      return byXPath(`//*[not(self::script) and (@aria-label=` + lit(n)
                     + ` or @title=` + lit(n) + ` or normalize-space(text())=` + lit(n) + `)]`);
    }
    if (sel.indexOf(`pierce/`) === 0) { sel = sel.slice(7); }
    return document.querySelector(sel);
  } catch (e) { return null; }
}
if (action === `exists`) {
  var body = document.body || document.documentElement;
  var txt = (body && (body.innerText || body.textContent)) || ``;
  return { ok: txt.indexOf(value) >= 0, used: null };
}
for (var i = 0; i < cands.length; i++) {
  var el = find(cands[i]);
  if (!el) { continue; }
  if (action === `click`) {
    try { el.scrollIntoView({ block: `center` }); } catch (e) {}
    el.click();
  } else if (action === `fill`) {
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event(`input`, { bubbles: true }));
    el.dispatchEvent(new Event(`change`, { bubbles: true }));
  }
  return { ok: true, used: cands[i] };
}
return { ok: false, used: null };
```

できること:

- **セレクタ候補を順に試す** — 先頭から探し、最初に見つかった要素を操作する（1 つ目が変わっても次で拾える）。
- **セレクタの書き方は録画 JSON と同じ** — `#id` や `.class`（CSS）、`xpath/…`、`text/表示文字`、`aria/表示名`。
- `action` は `"click"` / `"fill"` / `"exists"`（`exists` は画面に指定文字があるかの確認。完了メッセージの検証に使う）。
- 戻り値 `{"ok":true,"used":"実際に一致したセレクタ"}` — **`ok` が false ならその件を失敗**として扱う。

---

## 🔁 フローの組み立て

### 1. 準備（1 回だけ）

1. 「アプリケーションの実行」で `msedgedriver.exe --port=9515`
2. 「変数の設定」で `%JsAct%` に上記 JavaScript
3. 「Web サービスの呼び出し」で ①セッション開始 → 「JSON をカスタム オブジェクトに変換」→
   `%SessionId%` に `value.sessionId` を格納
4. ②ウィンドウサイズ、③ログイン画面を開く
5. ④で ID・パスワードを `fill`、ログインボタンを `click`
   - **資格情報はフローに直書きしない**。PAD の「資格情報」または暗号化変数を使う。

### 2. 明細を読む

「**CSV ファイルから読み取る**」で明細を `%Rows%` に読み込む（「最初の行に列名が含まれる」を ON）。
列は Python 版と同じ規約にする。

```csv
プロジェクト番号,発注番号,skip
PM9000000001,900000000001,
PM9000000002,900000000002,
PM9000000003,900000000003,1
```

- **先頭列（プロジェクト番号）が ID** — 進捗表示・結果 CSV・再実行はこの値で扱う。
- **skip 列に値がある行は飛ばす**（行を消さずに「今回は流さない」を表現できる）。

### 3. 明細ごとのループ

「**For each**」で `%Rows%` を回し、中を「**エラー発生時（On block error）**」で囲む。
1 件分の中身は、④の呼び出しを手順どおり並べるだけ。

```
For each %Row% in %Rows%
  If %Row['skip']% ≠ '' then  → 結果に「スキップ」を追加して Next
  On block error（例外時は「ブロックの最後に移動」＋失敗を記録）
    ④ click  [["#POS_ORDERS"]]
    ④ click  [["#POS_PURCHASE_ORDERS"]]
    ④ click  [["aria/拡張検索","#SrchBtn"]]
    ④ fill   [["#Value_0"]] , 値 = %Row['発注番号']%
    ④ click  [["aria/進む","#AdvGoBtn"]]
    ④ click  [["aria/%Row['発注番号']%"]]      ← セレクタに明細の値を埋める
    ④ click  [["#ActionGoBtn"]]
    ④ click  [["#ActionGoBtn"]]
    ④ click  [["#PosSubmitBtn"]]
    ④ exists 値 = "は確認されました。"          ← 完了の確認（ok=false なら失敗扱い）
    「スクリーンショットを取得」→ ファイル名 %Row['プロジェクト番号']%__%Row['発注番号']%__%日時%.png
    ④ click  [["aria/ホーム","#homeIcon"]]      ← 次の件のために起点へ戻る
  End
End
```

**ループの始点と終点は同じ画面にする**（ループ不変条件）。1 件の最後に「ホームへ戻る」を入れておけば、
次の件が必ず同じ状態から始まる。失敗時も同じ手順を「エラー発生時」の中で実行して復帰させる。

### 4. 結果の記録と再実行

- 各件の結果（ID／成功・失敗・スキップ／理由／エビデンスのパス）をデータテーブルに追加し、
  最後に「**CSV ファイルに書き込む**」で保存する。
- **失敗分だけの再実行**は、その結果 CSV を明細として読み込み、`結果` 列が `失敗` の行だけ回せばよい。
- 失敗時は「スクリーンショットを取得」で `fail_<ID>_日時.png` も保存しておくと原因調査が早い。

> **⚠️ 登録系の再実行は二重登録に注意。**「実は登録は成功していたが確認段階で失敗扱いになった」ことがある。
> 再実行の前に失敗時スクショで実際の画面を確認すること。

### 5. 後片付け

⑤ セッション終了（DELETE）→ 「アプリケーションの実行」で `taskkill /IM msedgedriver.exe /F`。

---

## 🧪 会社の環境が無くても練習できる

同梱の練習サイト `test_site/edi2/index.html` は、実 EBS と**同じ要素 ID**
（`#usernameField` / `#POS_ORDERS` / `#SrchBtn` / `#Value_0` / `#ActionGoBtn` / `#PosSubmitBtn` /
検索結果リンク `#N58:PosPoNumber:0`）で発注確認の流れを再現している。
**単一ファイルなので Python のサーバーは不要** — ファイルをダブルクリックして
`file:///…/test_site/edi2/index.html` で開けば動く（③のページを開く URL にこのパスを指定すればよい）。

ログインは `demo` / `password123`。この練習サイトで PAD のフローを完成させてから、
URL と資格情報だけを本番向けに差し替えるのが安全な進め方。

---

## 📄 手順書の自動生成（自宅で使う）

自宅の Python 環境で、**PAD が送るのと同じ HTTP 呼び出しを同じ順序で送る参照実装**を用意している。
実際に練習サイトへ流して成功を確認しつつ、その呼び出し列を Markdown の表として書き出せる。

```powershell
# 別ターミナルで: msedgedriver.exe --port=9515
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json `
    --details data/edi2_practice_batch.csv --trace output/pad_trace.md
```

`output/pad_trace.md` に「何番目に・どのメソッドで・どの URL へ・どんな本文を送るか」が全件出力される
（セッション ID は `{session}` に伏せ、秘密情報は `[SECRET:名前]` の表記で残らない）。
**バッチ定義 JSON を変えれば、その業務の手順書がそのまま生成される**ので、
フロー 2（納入登録）・フロー 3（エビデンス取得）でも同じ手順で PAD 版を起こせる。

---

## ❓ うまくいかないとき

| 症状 | 確認すること |
|---|---|
| ①で接続できない | `msedgedriver.exe` が起動しているか、ポート 9515、プロキシ除外に `localhost` |
| ①で `session not created` | **Edge とドライバのバージョン不一致**（Edge 更新後によく起きる） |
| ④が `ok:false` | セレクタ候補が古い。画面を F12 で確認して候補を足す。画面遷移の直後なら待機を入れる |
| 画面遷移が間に合わない | ④の前に「待機」を 1〜2 秒入れるか、`exists` で目的の文字が出るまでループする |
| 日本語が化ける | 「Web サービスの呼び出し」のエンコードを UTF-8 にする |
| 実行後もブラウザが残る | ⑤の DELETE と `taskkill` を最後に必ず通す（エラー時も通るようにする） |
