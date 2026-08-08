# PAD + WebDriver の内部設計と、実機で分かったこと

このページは「作る人・直す人」向け。使い方は [PAD_WebDriver.md](PAD_WebDriver.md) を参照。

生成器（`tools/pad_converter.html` / `pad_webdriver_ref.py`）がどういう考えで
組み立てているか、そして **Power Automate Desktop 無料版 (PAD) の実機で
分かった書式の癖**をまとめてある。後者は公式に書かれていないものが多く、
このプロジェクトで 1 つずつ確かめた結果。

---

## 📖 目次

**設計**　[🔌 使う HTTP 呼び出しは 6 種類だけ](#-使う-http-呼び出しは-6-種類だけ) / [📜 共通 JavaScript（変数 `%JsAct%` に入れておく）](#-共通-javascript変数-jsact-に入れておく) / [🔁 フローの組み立て](#-フローの組み立て) / [📸 エビデンスの撮り方](#-エビデンスの撮り方) / [🔐 自動ログインへの設計変更](#-自動ログインへの設計変更)
**実機で分かったこと**　[⚠️ Web.InvokeWebService の引数（最重要）](#-webinvokewebservice-の引数最重要) / [📌 Robin リテラルのエスケープ（実機で判明）](#-robin-リテラルのエスケープ実機で判明) / [✅ 実機で確認できたアクション書式（PAD 無料版 / Windows 11）](#-実機で確認できたアクション書式pad-無料版--windows-11)
**Python 版限定**　[📄 手順書の自動生成（Pythonが使える環境で使う）](#-手順書の自動生成pythonが使える環境で使う)

---

# 第 1 部　設計

---

## 🔌 使う HTTP 呼び出しは 6 種類だけ

| 目的 | メソッド | URL | 本文 |
| --- | --- | --- | --- |
| ① セッション開始（ブラウザ起動） | POST | `http://127.0.0.1:9515/session` | `{"capabilities":{"alwaysMatch":{"browserName":"MicrosoftEdge"}}}` |
| ② ウィンドウサイズ | POST | `…/session/%SessionId%/window/rect` | `{"width":1920,"height":1080}` |
| ③ ページを開く | POST | `…/session/%SessionId%/url` | `{"url":"https://…"}` |
| ④ **クリック／入力／文字確認（共通）** | POST | `…/session/%SessionId%/execute/sync` | `{"script":"%JsAct%","args":[[セレクタ候補],"click"/"fill"/"exists","値"]}` |
| ⑤ **スクリーンショット** | GET | `…/session/%SessionId%/screenshot` | （なし） |
| ⑥ セッション終了 | DELETE | `…/session/%SessionId%` | （なし） |

`Web.Method.Post` / `Web.Method.Get` / `Web.Method.Delete` はいずれも実機で有効。

① の応答から `sessionId` を取り出し、以降で使う URL を先に組み立てておくと 1 行が短く保てる。

```
Variables.ConvertJsonToCustomObject Json: SessionResp CustomObject=> SessionObj
SET SessionId TO SessionObj['value']['sessionId']
SET ExecUrl TO $'''%DriverUrl%/session/%SessionId%/execute/sync'''
SET GoUrl TO $'''%DriverUrl%/session/%SessionId%/url'''
SET RectUrl TO $'''%DriverUrl%/session/%SessionId%/window/rect'''
SET ShotUrl TO $'''%DriverUrl%/session/%SessionId%/screenshot'''
SET QuitUrl TO $'''%DriverUrl%/session/%SessionId%'''
```

### カスタムオブジェクトはブラケット記法で参照する

```
SET SessionId TO SessionObj['value']['sessionId']    ← 正しい
SET SessionId TO SessionObj.value.sessionId          ← 動かない
```

WebDriver の応答は常に `{"value": …}` で包まれているので、`['value']` を経由するのが基本形。

> **要素の操作を ④ に一本化するのがコツ。** W3C 標準の「要素を検索して要素 ID を得る →
> その ID を操作する」方式は往復が増え、`element-6066-11e4-a52e-4f735466cecf` という長いキーの
> 取り回しが PAD では煩雑になる。④ の JavaScript 方式なら、**PAD 側は同じ形のアクション 1 種類**を
> 用意し、`args` だけ差し替えればよい。

---

---

## 📜 共通 JavaScript（変数 `%JsAct%` に入れておく）
Pythonで作ったコア部分、DOMベース要素インデックスモジュールをJavaScriptで作り直したプログラムをRobinに埋め込むことで実現している。

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

- **セレクタ候補を順に試す** — 先頭から探し、最初に見つかった要素を操作する（1 つ目が変わっても
  次で拾える）。
- **セレクタの書き方は録画 JSON と同じ** — `#id` や `.class`（CSS）、`xpath/…`、`text/表示文字`、
  `aria/表示名`、`pierce/…`。
- `action` は `click` / `fill` / `exists`（`exists` は画面に指定文字があるかの確認。
  完了メッセージの検証に使う）。
- 戻り値 `{"ok":true,"used":"実際に一致したセレクタ"}` — **`ok` が false ならその件を失敗**として扱う。
  `used` を残しておくと、どの候補で当たったかがデバッグ時に分かる。

呼び出し側は毎回この形になる。

```
SET ActBody TO $'''{"script": "%JsAct%", "args": [["#btn-search", "aria/検索"], "click", ""]}'''
Web.InvokeWebService.InvokeWebService Url: ExecUrl Method: Web.Method.Post Accept: AppJson ContentType: AppJson RequestBody: ActBody EncodeRequestBody: False FailOnErrorStatus: False Response=> ActResp StatusCode=> ActStatus
Variables.ConvertJsonToCustomObject Json: ActResp CustomObject=> ActObj
IF ActObj['value']['ok'] <> True THEN
    SET RowError TO $'''ステップN（click #btn-search）で要素が見つかりません'''
END
```

> **隠れている要素に注意。** `querySelector` は `display:none` の要素も返す。`el.click()` は
> 見えない要素でも `onclick` を発火させるため、「検索 0 件なのに次へ進んでしまう」ことがある。
> 対象の画面がヒット時だけ行を生成する作りなら問題ないが、`hidden` クラスで隠すだけの作りなら
> `find()` に可視判定を足すか、`exists` で件数表示を確認する。





---

---

## 🔁 フローの組み立て

1 件動かすのと、数十件を安全に流すのは別の問題。次の 3 部構成にする。

```
setup   … ドライバ起動 → セッション → ログイン → ループの起点へ移動 → 失敗検知
loop    … 1 件分の処理を繰り返す
recover … 失敗した件のあと、次の件の前に起点へ戻す
```

### 1. セットアップ（最初に 1 回実行する部分）

1. 古いドライバーを終了 → `msedgedriver.exe --port=9515` を起動
2. `%JsAct%` を用意（継ぎ足しまたはファイル読み込み）
3. ① セッション開始 → `%SessionId%` と各 URL を組み立て
4. ② ウィンドウサイズ、③ 対象ページを開く
5. **手動ログイン**（→ 次節）
6. **ループの起点へ移動**（ループ不変条件をそろえるための一手）

### 2. セットアップ失敗を検知して止める ★重要

手動ログインや起点への移動に失敗したまま明細ループに入ると、**全件が「ステップ 1 で要素が
見つかりません」という偽の失敗になる。** 本当の原因が結果 CSV から読み取れなくなり、
再実行時に「本当に未処理か」を 1 件ずつ確認する手間が発生する。

```
IF RowError <> $'''''' THEN
    SET Halt TO True
END
IF Halt = False THEN
    …CSV 読み込みとループ全体…
END
```

### 3. 明細を読む

「**CSV ファイルから読み取る**」で明細を `%Rows%` に読み込む（「最初の行に列名が含まれる」を ON）。

```
プロジェクト番号,発注番号,skip
PM9000000001,900000000001,
PM9000000002,900000000002,
PM9000000003,900000000003,1
```

- **先頭列（プロジェクト番号）が ID** — 進捗表示・結果 CSV・再実行はこの値で扱う。
- **skip 列に値がある行は飛ばす**（行を消さずに「今回は流さない」を表現できる）。

### 4. 件数制限設定

いきなり全件流さないための安全弁。本番初回は 1 件にして、画面と結果を目で確認してから件数を増やす。

```
IF Attempted >= MaxItems THEN
    File.WriteText … $'''%Col1%,%Col2%,未実行,"件数上限 %MaxItems% 件に達したため",,'''
    NEXT LOOP
END
SET Attempted TO Attempted + 1
```

**打ち切った行を「未実行」として記録に残す**のが要点。どこから再開すればよいかが分かる。

### 5. 明細ごとのループ（繰り返す部分）

```
LOOP FOREACH Row IN Rows
    SET Col1 TO Row['プロジェクト番号']
    SET Col2 TO Row['発注番号']
    SET RowError TO $''''''

    …再実行モードの絞り込み / skip 判定 / 件数上限（いずれも NEXT LOOP）…

    IF PrevFailed THEN
        …起点へ戻る操作…
        SET PrevFailed TO False
    END
    SET PrevFailed TO True          # ← 悲観的に置く

    …④ の呼び出しを手順どおり並べる。各ステップの後で ok を判定し、
      失敗ならエビデンスと結果 CSV を書いて NEXT LOOP…

    …エビデンス保存…
    …起点へ戻る…

    SET PrevFailed TO False         # ← 最後まで通ったらここで戻す
    SET OkCount TO OkCount + 1
END
```

**ループの始点と終点は同じ画面にする**（ループ不変条件）。1 件の最後に「起点へ戻る」を
入れておけば、次の件が必ず同じ状態から始まる。これが崩れると、2 件目以降の失敗理由が
「要素が見つからない」ばかりになって原因が追えない。

### 6. 失敗後の復帰 ★重要

**失敗した画面のまま次の件を始めると、1 件の失敗が全件に連鎖する。**
フラグを立てる箇所を 1 つに減らすには、上のような**悲観的な初期化**が使える。
`SET PrevFailed TO True` を件の先頭に置き、最後まで通ったときだけ `False` に戻す。
失敗経路が何箇所あっても 1 行で済む。

実機では、発行完了後に意図的に失敗させた次の行が 18 秒後に正常完了することを確認した。

---

---

## 📸 エビデンスの撮り方

### PAD の標準アクションは全画面

`Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile` は**デスクトップ全体**を撮る。
他のウィンドウやメールの件名まで写り込むため、証跡として扱いにくく、情報管理の面でも避けたい。

### WebDriver に撮らせる（推奨）

`GET /session/{id}/screenshot` は**ページの表示領域だけ**を Base64 の PNG で返す。

```
Web.InvokeWebService.InvokeWebService Url: ShotUrl Method: Web.Method.Get Accept: AppJson ContentType: AppJson EncodeRequestBody: False FailOnErrorStatus: False Response=> ShotResp StatusCode=> ShotStatus
Variables.ConvertJsonToCustomObject Json: ShotResp CustomObject=> ShotObj
SET ShotB64 TO ShotObj['value']
File.ConvertFromBase64 Base64Text: ShotB64 File: ShotPath IfFileExists: File.IfExists.DoNothing
```

利点が 3 つある。

- **フォーカスに依存しない。** 実行中に通知ウィンドウが前面に出ても影響しない
- **他のウィンドウが写り込まない**
- ブラウザーの枠や URL バーが入らない

制約は 1 つ、**スクロールしないと見えない範囲は写らない。** 完了メッセージが下方に出る画面では、
ウィンドウを縦長にするか、撮る直前に先頭へスクロールする。

`ShotObj` / `ShotResp` は `ActObj` / `ActResp` と**別の変数名にする**。使い回すと直前の `ok` 判定を
壊す。

### 列挙型の名前空間がアクションごとに違う

```
File.WriteText            … IfFileExists: File.IfFileExists.Append / Overwrite
File.ConvertFromBase64    … IfFileExists: File.IfExists.DoNothing / Overwrite
```

`IfFileExists` と `IfExists` で別物。デザイナーから 1 つ生成して確認するのが確実。

### `DoNothing` の静かな失敗

`File.ConvertFromBase64` は書き込めなくてもエラーを出さずに通過する。
**結果 CSV にパスが書かれていることは、ファイルが存在する証拠にならない。**
検証時は実体を必ず目で確認すること。

---

## 🔐 自動ログインへの設計変更

### 後で自動ログインに設計変更したくなった時の注意点

やむを得ず自動化を考える場合は・・・

- フローに直書きしない（`SET Pw TO $'''abc123'''` は作らない）
- 入力ダイアログの［入力の種類］を「パスワード」にする
- 結果 CSV とログに変数を出さない
- ログイン失敗時の理由は固定文字列にする（エラー本文には送信した JSON = パスワードが
  含まれることがある）
- 使い終わったら `SET Pw TO $''''''` で消す
- `"` と `\` を含むパスワードは JSON 本文を壊すため、`\` → `\\`、`"` → `\"` の順で
  エスケープする

エスケープの書式は実機で確認済み。**アクション名は `Text.Replace.ReplaceText`**（`Text.Replace`
では通らない）。`ComparisonType` が必須で、正規表現を使わない場合は `IsRegEx:` を書かない。

```
Text.Replace.ReplaceText Text: EdiPassword TextToFind: $'''\\''' IgnoreCase: False ReplaceWith: $'''\\\\''' ActivateEscapeSequences: False ComparisonType: Text.TextComparisonType.CultureSensitive Result=> PwSafe
Text.Replace.ReplaceText Text: PwSafe TextToFind: $'''\"''' IgnoreCase: False ReplaceWith: $'''\\\"''' ActivateEscapeSequences: False ComparisonType: Text.TextComparisonType.CultureSensitive Result=> PwSafe
```

**バックスラッシュを先に処理する順序を守ること。** 逆にすると、1 段目で入れた `\\` を
2 段目がさらに書き換えてしまう。

**`ActivateEscapeSequences: False` が重要。** `True` にすると置き換え先の `\\` が
エスケープ列として解釈されてバックスラッシュ 1 個に戻り、意図が反転する。

上の例は PAD から取り出した正規形なので二重引用符が `\"` になっているが、**リテラル内では
`"` と `\"` は同じ意味**なので、素の `"` で書いても等価。生成器は後者（素の `"`）で出力する。
そのほうがパス以外に単独のバックスラッシュが残らず、「バックスラッシュは必ず二重化する」
という規則を機械的に検査できる。

ダイアログとの対応:

| ダイアログ | Robin |
| --- | --- |
| 解析するテキスト | `Text:` |
| 検索するテキスト | `TextToFind:` |
| 検索と置換に正規表現を使う | `IsRegEx:`（オフなら省略される） |
| 大文字と小文字を区別しない | `IgnoreCase:` |
| 置き換え先のテキスト | `ReplaceWith:` |
| エスケープ シーケンスをアクティブ化 | `ActivateEscapeSequences:` |
| 比較の種類 | `ComparisonType:`（既定 `Text.TextComparisonType.CultureSensitive`） |
| 生成された変数 | `Result=>`（既定名 `Replaced`） |


---

---

# 第 2 部　実機で分かったこと

---

## ⚠️ Web.InvokeWebService の引数（最重要）

**ここを外すと何ひとつ動かない。** 実機で確定した書式は次のとおり。

```
Web.InvokeWebService.InvokeWebService Url: ExecUrl Method: Web.Method.Post Accept: AppJson ContentType: AppJson RequestBody: ActBody EncodeRequestBody: False FailOnErrorStatus: False Response=> ActResp StatusCode=> ActStatus
```

### `EncodeRequestBody: False` が必須

既定では本文が URL エンコードされて送信され、WebDriver は
`invalid argument: missing command parameters` を返す。**この 1 語が最大の関門だった。**

### `Url:` であって `URL:` ではない

大文字にすると引数として認識されない。

### `FailOnErrorStatus: False` を付ける

WebDriver は要素が見つからない等で 4xx/5xx を返す。既定のままだとフローがそこで停止するため、
バッチ処理にならない。`False` にして、成否はレスポンス JSON の `ok` で判定する。

### 存在しない引数

以下は PAD の `Web.InvokeWebService` には**ない**。書くと貼り付けが失敗する。

- `ConnectionTimeout`
- `FollowRedirection`
- `ClearCookies`
- `Encoding`（`Web.Encoding.Utf8` / `Web.FileEncoding.UTF8` いずれも不可）

> 初版に「日本語が化けるならエンコードを UTF-8 にする」と書いていたが、**この引数は存在しない**。
> 日本語は既定で正しく送れている。

---

---

## 📌 Robin リテラルのエスケープ（実機で判明）

PAD は貼り付けたテキストを解釈できないと**エラーも出さず黙って無視する**。原因は 2 系統ある。

### 系統 1: エスケープ

| 文字 | リテラル内の書き方 | 理由 |
| --- | --- | --- |
| 単引用符 `'` | `\'` にエスケープ（または使わない） | 生のままだと貼り付けが無視される |
| バックスラッシュ `\` | **`\\` に二重化** | `\%` が「エスケープされた %」と解釈され、変数展開の `%` が対応せず失敗する |
| 二重引用符 `"` | `"` でも `\"` でもよい | PAD から取り出すと `\"` に正規化される |
| 波かっこ `{ }`・角かっこ `[ ]`・比較演算子 | そのまま | 問題なし |

`$'''%OutDir%\%ShotName%.png'''` は貼り付けできず、`$'''%OutDir%\\%ShotName%.png'''` なら通る。

### 系統 2: 1 行の長さ

**長すぎる 1 行も黙って無視される。** 約 300 文字・約 700 文字は通るが、共通 JavaScript
（約 1,700 文字）を 1 つの `SET` に入れると無視される。

対処は 2 つある。

- **変数への継ぎ足しで組み立てる**（推奨）。1 行 100 文字程度に分ければ確実に通る。
  ```
  SET JsAct TO $'''前半…'''
  SET JsAct TO $'''%JsAct%後半…'''
  ```
- **共通 JavaScript を丸ごと貼る。** 「変数の設定」アクションを 1 つ置き、値の欄に
  中身を直接貼る（UI の入力欄なら長い文字列でも入る）。変数名は `JsAct`。
  中身はブラウザ版の「共通 JavaScript をコピー」で取るか、Python 版が同時に出力する
  `pad_flow.jsact.js` から取る。
  **ブラウザ版にファイル保存の機能は無い。** 単体のスクリプトファイルはウイルス対策に
  ブロックされ、`.txt` にリネームしても同じだった（拡張子ではなく中身が検知される）。

### 系統 3: 変数の渡し方

```
File: ShotPath            ← 正しい（変数の中身が渡る）
File: $'''ShotPath'''     ← 誤り（"ShotPath" という文字列になる）
```

これは**静かに失敗する**ので厄介。「ShotPath」という名前のファイルが作られたり、Base64 として
解釈できない文字列が渡ったりする。

### 生成コードが単引用符を避けている理由

- **JavaScript の文字列はバックティック** `` `…` `` で書く（`'` も `"` も使わない）。
  実行時に単引用符が必要な箇所は `String.fromCharCode(39)` で作る。
- **`{{列名}}` は `%Row['列名']%` にしない。** ループ先頭で `SET Col1 TO Row['プロジェクト番号']` のように
  変数へ取り出し、リテラル内では `%Col1%` を使う（`SET` 行の `'` はリテラルの外なので問題ない）。
- **`xpath///*[@id="X"]` は `id/X` に変換**する（JS 側が `document.getElementById` で解決する）。
  引用符が残る候補は生成時に除外される。

### 切り分けの手順

一括貼り付けが無視される場合は、「設定〜セッション開始」「セットアップ」「ループ」「後片付け」の
4 ブロックに分けて貼ると、どこで弾かれているか特定できる。1 行だけ弾かれている場合は、
その行のアクション名が PAD のバージョンと違う可能性が高い。**PAD で同じアクションを 1 つ
キャンバスに置いてコピー（Ctrl+C）し、テキストに貼れば、その環境での正しい書式が分かる。**

---

---

## ✅ 実機で確認できたアクション書式（PAD 無料版 / Windows 11）

| 用途 | Robin |
| --- | --- |
| プロセス終了 | `System.TerminateProcess.TerminateProcessByName ProcessName:` |
| WebDriver 起動 | `System.RunApplication.RunApplication ApplicationPath: CommandLineArguments: WindowStyle: System.ProcessWindowStyle.Hidden ProcessId=>` |
| HTTP 呼び出し | `Web.InvokeWebService.InvokeWebService`（引数は上記の節） |
| JSON 解析 | `Variables.ConvertJsonToCustomObject Json: CustomObject=>` |
| CSV 読み込み | `File.ReadFromCSVFile.ReadCSV CSVFile: Encoding: File.CSVEncoding.UTF8 TrimFields: FirstLineContainsColumnNames: ColumnsSeparator: File.CSVColumnsSeparator.Comma CSVTable=>` |
| テキスト追記 | `File.WriteText File: TextToWrite: AppendNewLine: IfFileExists: File.IfFileExists.Append` |
| Base64 → ファイル | `File.ConvertFromBase64 Base64Text: File: IfFileExists: File.IfExists.DoNothing` |
| 全画面スクショ | `Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile File: ImageFormat: System.ImageFormat.Png` |
| 現在日時 | `DateTime.GetCurrentDateTime.Local DateTimeFormat: DateTime.DateTimeFormat.DateAndTime CurrentDateTime=>` |
| 日時 → テキスト | `Text.ConvertDateTimeToText.FromCustomDateTime DateTime: CustomFormat: Result=>` |
| ダイアログ | `Display.ShowMessageDialog.ShowMessage Title: Message: Icon: Buttons: Display.Buttons.OKCancel DefaultButton: IsTopMost: ButtonPressed=>` |
| テキストの置換 | `Text.Replace.ReplaceText Text: TextToFind: IgnoreCase: ReplaceWith: ActivateEscapeSequences: ComparisonType: Text.TextComparisonType.CultureSensitive Result=>` |
| フォルダー作成 | `Folder.Create FolderPath: FolderName: Folder=>` |
| フォルダー内のファイル取得 | `Folder.GetFiles Folder: FileFilter: IncludeSubfolders: FailOnAccessDenied: SortBy1: Folder.SortBy.Name SortDescending1: … Files=>` |
| ファイル名の変更 | `File.RenameFiles.Rename Files: NewName: KeepExtension: IfFileExists: File.IfExists.Overwrite RenamedFiles=>` |
| ループ / 条件 / 変数 | `LOOP FOREACH … IN … END` / `NEXT LOOP` / `IF … THEN … END` / `SET … TO …` / `LOOP WHILE … END` |

`LOOP FOREACH` の内側でネストした `IF` と `NEXT LOOP` も正常に動作する。

> 初版では CSV 読み込みを `File.ReadCsvFile.ReadCsvFile` と記載していたが、**これは誤り**。
> 正しくは `File.ReadFromCSVFile.ReadCSV` である。

**`IF StatusCode <> 200 THEN`** … `Web.InvokeWebService` の `StatusCode=>` は数値として
比較できる（実機確認: `BrowserName` を存在しない値にしてセッション作成を失敗させ、
`session not created: No matching capabilities found` を含む生の応答をダイアログに表示できた）。
文字列リテラルとの比較にする必要はない。

### 🚫 無効だった引数・構文

**`Display.Icon.Error`** … PAD の画面には「エラー」のアイコンがあるが、この綴りで書いた行は
貼り付け時に黙って落ちた（2026/08/02、PAD 無料版 / Windows 11）。確認済みは
`Information` / `Warning` / `Question` / `None`。**UI に選択肢があっても Robin の綴りが
同じとは限らない。** 生成器の lint に既知の列挙値の表を持たせて、外れた値を警告するようにした。


- `AfterCompletion`
- `Encoding: Web.Encoding.Utf8`（`Web.InvokeWebService` にエンコード引数は無い）
- `EXIT FUNCTION`
- `Web.InvokeWebService` の `ConnectionTimeout` / `FollowRedirection` / `ClearCookies` / `Encoding`
- `URL:`（正しくは `Url:`）
- `Folder.SortBy1.NoSort` / `Folder.SortBy2.…` / `Folder.SortBy3.…`
  （正しい名前空間は **`Folder.SortBy`**。確認済みの値は `Name` / `FullName` /
  `LastModified` / `LastAccessed`）
- `File.RenameFiles.RenameByReplacingText`（「新しい名前を設定する」は
  **`File.RenameFiles.Rename`**）

---

---

# 第 3 部　Python 版限定

---

## 📄 手順書の自動生成（Pythonが使える環境で使う）

変換環境（Python が使える PC）向けに、**PAD が送るのと同じ HTTP 呼び出しを同じ順序で送る参照実装**を用意している。
実際に練習サイトへ流して成功を確認しつつ、その呼び出し列を**Markdown の表として書き出せるので、資料作成に使える。**

```
# 別ターミナルで: msedgedriver.exe --port=9515
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json `
    --details data/edi2_practice_batch.csv --trace output/pad_trace.md
```

`output/pad_trace.md` に「何番目に・どのメソッドで・どの URL へ・どんな本文を送るか」が
全件出力される（セッション ID は `{session}` に伏せ、秘密情報は `[SECRET:名前]` の表記で残らない）。
**バッチ定義 JSON を変えれば、その業務の手順書がそのまま生成される。**

---
