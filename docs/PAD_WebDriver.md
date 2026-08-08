# Power Automate Desktop 無料版 (PAD) と WebDriver だけでバッチ実行する（ブラウザ拡張機能は不要）

Power Automate Desktop 無料版（PAD）の Web 自動化アクションは専用のブラウザ拡張機能を必要とするが、
**WebDriver はブラウザ拡張機能が無くても動作する。** `msedgedriver.exe` 自体がローカルの HTTP サーバーとして動く。
つまり **HTTP リクエストを送れれば、拡張機能なしでブラウザを完全に操作できる**。
PAD の「Web サービスの呼び出し」がまさにそれに当たる。

このドキュメントは、`run_batch.py`（Python 版バッチランナー）と同じことを、
**Python を使わず PAD だけで**実現するため Python 版のコア部分のDOMベース要素インデックスモジュールを JavaScript で作り直したプログラムを埋め込むことで実現した。

企業環境では次のような制約が同時に成立することがある。この手法はそこを通り抜けるためのもの。

- ブラウザー拡張機能のインストールが禁止されている。
- Python / Node.js などの開発ツールがインストールできない。
- PowerShell スクリプトの実行が禁止されている。
- Proxy Server を使用している環境。
- 一方で Power Automate Desktop 無料版 (PAD) と WebDriver は使える。


**実機（Power Automate Desktop 無料版 (PAD) / Windows 11 / Edge）で完走を確認済み。** 以下の記述は原則として実機で
確認できた内容を明記している。


---

> **このページは「使う人」向け。** 導入から実行までの手順をまとめている。
> 生成器の設計や、実機で分かった PAD の癖は
> [PAD_WebDriver_internals.md](PAD_WebDriver_internals.md) に分けてある。

---

## 📖 目次

**はじめに**　[💡Power Automate Desktop 無料版 (PAD) 標準の録画機能との違い](#power-automate-desktop-無料版-pad-標準の録画機能との違い) / [🧭 全体像](#-全体像) <br>
**準備**　[🛠️ 事前準備](#-事前準備) / [🌐 プロキシ経由でインターネットへ出る環境（企業のネット環境に多い）](#-プロキシ経由でインターネットへ出る環境企業のネット環境に多い) / [🔄 自動 WebDriver 取得更新機能　(`selenium-manager-windows.exe` 必要)](#-自動-webdriver-取得更新機能-selenium-manager-windowsexe-必要) <br>
**使い方**　[🤖 録画JSONファイルをPADコード(Robin)へ変換する](#-録画jsonファイルをpadコードrobinへ変換する) <br>
**運用**　[🔐 資格情報の扱い](#-資格情報の扱い) / [📊 結果 CSV と再実行](#-結果-csv-と再実行) / [📸 エビデンス（スクリーンショット）](#-エビデンススクリーンショット) / [📥 ファイルのダウンロード（エビデンスが画面に出ない場合）](#-ファイルのダウンロードエビデンスが画面に出ない場合) / [🕒 日時とファイル名](#-日時とファイル名) <br>
**練習**　[🧪 実環境が無くても練習できる](#-実環境が無くても練習できる) / [📦 サンプル](#-サンプル) <br>
**困ったとき**　[❓ うまくいかないとき](#-うまくいかないとき) / [⚠️ 制約](#-制約)

---

## 💡Power Automate Desktop 無料版 (PAD) 標準の録画機能との違い

本ツール
- ブラウザ自動化バッチ処理に特化し、バッチ運用フロー設定を自動追加し、はまり回避対策をしたPADコード(Robin)に変換する設計。
- DevTools Recorder機能があるブラウザさえあれば操作録画できる。
- 全体のフロー制御はPADを使うが、主なブラウザのコントロールやDOMベース要素インデックス方式はJavaScriptで作ったプログラムをRobinに埋め込み実現。
- 直接WebDriverを操作するのでブラウザ拡張機能なしで使える。

Power Automate Desktop 無料版 (PAD)
- PAD標準の操作録画機能は全般的な用途に使えるように操作をアクションとしてそのまま登録するだけになっている。



---

---

## 🧭 全体像

```
┌──────────────────────────┐
│ Power Automate Desktop   │
│  Web.InvokeWebService    │  ← 標準アクション。ブラウザ拡張機能は不要。
└────────────┬─────────────┘
             │ HTTP + JSON (W3C WebDriver)
             │ http://127.0.0.1:9515
┌────────────▼─────────────────────────────┐
│ msedgedriver.exe または chromedriver.exe  │  ← System.RunApplication で起動。
└────────────┬─────────────────────────────┘
             │ DevTools Protocol
┌────────────▼────────────────────────┐
│ Microsoft Edge または Google Chrome  │
└─────────────────────────────────────┘
```

| 役割 | 担当 |
| --- | --- |
| 明細（Excel/CSV）の読み込み、件数ループ、skip 判定、進捗、結果 CSV、リトライ | **PAD の標準アクション** |
| ブラウザの起動・画面遷移・クリック・入力・スクショ | **WebDriver**（PAD から HTTP で指示） |

Python 版との対応:

| Python 版 (`run_batch.py`) | PAD 版 |
| --- | --- |
| `--details` の CSV/xlsx 読み込み | 「CSV ファイルから読み取る」 |
| 明細ごとのループ | 「For each」 |
| `skip` 列 | 「If」 |
| `--max-items` | カウンタ変数 + 「If」 |
| `setup` / `loop` / `recover` | 同じ 3 部構成（サブフローに分けてもよい） |
| 失敗しても次の件へ | `FailOnErrorStatus: False` + `ok` 判定 + `NEXT LOOP` |
| `--retry-from` | 結果 CSV を明細として読み直す（`RetryMode`） |
| 進捗表示 | 「テキストをファイルに書き込む」 |
| 結果 CSV | 「テキストをファイルに書き込む」（追記） |
| エビデンスのスクショ | WebDriver の `/screenshot` + 「Base64 をファイルに変換する」 |

> 初版では「失敗しても次の件へ」を PAD の［エラー発生時（On block error）］で実現する想定だった。
> しかし `FailOnErrorStatus: False` を指定すると HTTP エラーでフローが止まらないため、
> **［エラー発生時］は不要**であることが実機で判明した。現在は `ok` 判定と `NEXT LOOP` で
> 制御している。

---

---

# 第 1 部　準備

---

## 🛠️ 事前準備

1. **💡本ツールは自動でブラウザのバージョンをチェックして、同じバージョンの WebDriver を自動取得し入れ替える機能がある。（後述）**　　

　　もし、WebDriverを自動取得できない環境の場合は手動でダウンロードする。 <br>
　　[Microsoft Edge を自動操作する場合の WebDriver](https://developer.microsoft.com/ja-jp/microsoft-edge/tools/webdriver?form=MA13LH&cs=3787589721) から **msedgedriver.exe** をダウンロードする。　<br>
　　[Google Chrome を自動操作する場合の WebDriver](https://developer.chrome.com/docs/chromedriver?hl=ja) から **chromedriver.exe** をダウンロードする。 <br>

 　　**⚠️ブラウザのバージョンとWebDriverのバージョンは一致させる必要がある。** <br>
 　　ブラウザのバージョンが更新されたら同じバージョンに入れ替える。　<br>

　　msedgedriver.exe と chromedriver.exe は技術的にはどちらもChromiumエンジンを基にしているため、 <br>
　　コードの書き方やAPI（操作コマンド）、DevTools は、ほぼ共通で違いはごくわずかで、ほぼ対象ブラウザが Edge か Chrome かの違い。<br>

2. **プロキシ除外**: 社内プロキシがあると `localhost` 宛が失敗する。Windows のプロキシ設定で
   `localhost;127.0.0.1` を除外に入れる（Ollama で `NO_PROXY=localhost` を設定したのと同じ対策）。

3. **フローの先頭で古いドライバーを終了させる。** 前回の実行が異常終了すると
   `msedgedriver.exe` がポート 9515 を掴んだまま残り、新しいドライバーが起動できない。 <br>
   その状態では**古い方が応答してしまい**、ブラウザーとバージョンが違えば `session not created` になる。 <br>
   Edge と Chrome のフローを続けて動かす場合も同じポートを奪い合うため、両方を終了させておく。

```
System.TerminateProcess.TerminateProcessByName ProcessName: $'''msedgedriver'''
System.TerminateProcess.TerminateProcessByName ProcessName: $'''chromedriver'''
WAIT 1
System.RunApplication.RunApplication ApplicationPath: DriverExe CommandLineArguments: $'''--port=9515''' WindowStyle: System.ProcessWindowStyle.Hidden ProcessId=> DriverPid
WAIT 3
```

`taskkill` を「アプリケーションの実行」で呼ぶ必要はない。`System.TerminateProcess` で足りる。


---

---

## 🌐 プロキシ経由でインターネットへ出る環境（企業のネット環境に多い）

**WebDriver が起動するブラウザーは素のプロファイル**で立ち上がり、Windows のプロキシ設定を
引き継がない。そのため、手動のブラウザーでは見えるサイトが WebDriver 経由では真っ白になる。
`localhost` と `file://` はプロキシを通らないので、練習サイトだけは影響を受けない。

セッション開始の本文に `proxy` を渡すと解決する。生成物では冒頭のスイッチで切り替えられる。

```
SET UseProxy TO True
SET ProxyAddr TO $'''proxy.example.com:8080'''
…
SET SessionBody TO $'''{"capabilities": {"alwaysMatch": {"browserName": "MicrosoftEdge"}}}'''
IF UseProxy THEN
    SET SessionBody TO $'''{"capabilities": {"alwaysMatch": {"browserName": "MicrosoftEdge", "proxy": {"proxyType": "manual", "httpProxy": "%ProxyAddr%", "sslProxy": "%ProxyAddr%"}}}}'''
END
```

- SET UseProxy TO True か False　でプロキシ設定を切り替える。
- アドレスは **`host:port` の形**で書く（`http://` は付けない）。
- Edge / Chrome 系は `sslProxy` を見ないことがあるため、`httpProxy` と両方に同じ値を入れる。
- プロキシのアドレスは Windows の「設定 → ネットワークとインターネット → プロキシ」で確認できる。
  `netsh winhttp show proxy` が「直接アクセス」と出ても、ブラウザー側に設定されていることがある。

**フローを触る前にプロキシ自体を検証しておくと切り分けが速い。** コマンドプロンプトで次を実行し、
`HTTP/1.1 200` が返ればアドレスとポートは正しい。

```
curl -x http://proxy.example.com:8080 https://example.com -I
```

> **⚠️ 認証プロキシの場合**
> ユーザー名・パスワードを要求するプロキシでは `proxyType: manual` だけでは通らないことがある。
> まず認証なしで試し、通らなければネットワーク管理者に方式を確認する。



---

---

## 🔄 自動 WebDriver 取得更新機能　(`selenium-manager-windows.exe` 必要)

**Edge と Chromeブラウザ は自動更新される。** そのたびに `msedgedriver.exe` を同じバージョンに入れ替えないと
`session not created` で止まる。　これを手作業で追いかけるのは現実的でない。

自動にするため **Selenium Manager**（Selenium 公式の単体実行ファイルで、Python も Node.js も要らない）
を使用し、インストール済みブラウザーに対応するバージョンのWebDriverを自動で取得し更新する。

-⚠️`selenium-manager-windows.exe` をダウンロードし実行環境の `BaseDir`（例 `C:\temp`）に置いておく必要がある。 <br>
　　入手先: <https://github.com/SeleniumHQ/selenium_manager_artifacts/releases>

```
selenium-manager-windows.exe --browser edge --browser-version stable --output json
```

```json
{
  "logs": [ … ],
  "result": {
    "code": 0,
    "message": "",
    "driver_path": "C:\\Users\\…\\.cache\\selenium\\msedgedriver\\win64\\150.0.4078.105\\msedgedriver.exe",
    "browser_path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
  }
}
```

⚠️**置き場所がバージョン番号を含むフォルダになる**点に注意。固定パスを `DriverExe` に書くと
更新のたびに壊れるので、この  `result.driver_path` をフローが読み取って使う。

**Chrome でも同じ仕組みが使える。** 生成物の冒頭にある `Browser` を `chrome` に変えるだけで、
WebDriver へ渡すブラウザー名（`MicrosoftEdge` → `chrome`）、終了させるプロセス名
（`msedgedriver` → `chromedriver`）、Selenium Manager が取得するドライバーの 3 つが同時に切り替わる。

```
SET Browser TO $'''edge'''
SET BrowserName TO $'''MicrosoftEdge'''
SET DriverProc TO $'''msedgedriver'''
IF Browser = $'''chrome''' THEN
    SET BrowserName TO $'''chrome'''
    SET DriverProc TO $'''chromedriver'''
END
```

💡対象サイトがブラウザー判定で表示を変える場合や、片方で不具合が出たときの逃げ道としても使える。
生成時に決めておくなら `--pad-browser chrome` を付ける。

生成器に `--auto-driver` を付けると次の仕組みが入る。**スイッチは冒頭の設定にまとめてあり、
実際に取得を走らせる処理だけがドライバー起動の直前に置かれる。**

```
# --- ドライバーの入手方法 ---（冒頭の設定）
SET AutoDriver TO True
SET SmExe TO $'''selenium-manager-windows.exe'''
```


```
SET AutoDriver TO True
SET SmExe TO $'''selenium-manager-windows.exe'''
IF AutoDriver THEN
    SET SmArgs TO $'''%SmExe% --browser %Browser% --browser-version stable --output json'''
    IF UseProxy THEN
        SET SmArgs TO $'''%SmArgs% --proxy %ProxyAddr%'''
    END
    Scripting.RunDOSCommand.RunDOSCommandAndFailOnTimeout DOSCommandOrApplication: SmArgs WorkingDirectory: BaseDir Timeout: 300 StandardOutput=> SmOutput StandardError=> SmError ExitCode=> SmExit
    Variables.ConvertJsonToCustomObject Json: SmOutput CustomObject=> SmObj
    IF SmObj['result']['code'] = 0 THEN
        SET DriverExe TO SmObj['result']['driver_path']
    END
END
```

- **標準出力を受け取るのは「DOS コマンドの実行」**（`Scripting.RunDOSCommand`）。これまで使ってきた
  「アプリケーションの実行」では出力を受け取れない。
- **社内プロキシ環境ではドライバーのダウンロードもプロキシ経由**になるため、`--proxy` が要る。
  `UseProxy` が `True` のときだけ自動で付く。
- 初回はダウンロードが走るので `Timeout` は長め（300 秒）にしておく。2 回目以降はキャッシュから返る。
- `ELSE` を使わず `IF code = 0` と `IF code <> 0` の 2 つに分けている（未検証の構文を避けるため）。
- 取得に失敗したときは `Halt` を立てて**ドライバー起動そのものに入らない**。ここで止めないと、
  更新前の古い固定パスで起動してしまい、症状が「セッション作成の失敗」に化けて原因が読めなくなる。

### ドライバーとブラウザーの照合を目に見える形にする

`AutoDriver` は「合っているはず」を前提にしていて、実際に何が起動したのかは出てこなかった。
セッションを張った直後に、応答の `capabilities` から**実際に動いているもの**を取り出して
ログとダイアログに出す。

```
SET BrowserVer TO SessionObj['value']['capabilities']['browserVersion']
SET DriverVer TO $'''(不明)'''
IF Browser = $'''chrome''' THEN
    SET DriverVer TO SessionObj['value']['capabilities']['chrome']['chromedriverVersion']
END
IF Browser = $'''edge''' THEN
    SET DriverVer TO SessionObj['value']['capabilities']['msedge']['msedgedriverVersion']
END
```

出力はこの 1 行。`ShowDriverInfo` を `False` にするとダイアログは出ないが、ログには必ず残る。

```
[ドライバー] ブラウザー=chrome 151.0.7922.72 / WebDriver=chromedriver 151.0.7922.72 (…) /
メジャー判定=一致 / 取得方法=Selenium Manager（ブラウザーのバージョンに合わせて自動取得）/ パス=…
```

- **比較するのはメジャーバージョンだけ。** Chrome とドライバーはビルド番号まで一致するとは
  限らない（ブラウザー 115.0.5790.110 に対しドライバー 115.0.5790.102 など）。完全一致で
  判定すると、正常な組み合わせを不一致と報告してしまう。
- **メジャーの取り出しはページ側の JavaScript にやらせている。** PAD のテキスト分割アクションを
  増やさずに済み、貼り付け時に黙って落ちる行を作らない。`/session/…/execute/sync` は
  すでに使っている呼び出しなので、新しい仕組みは何も増えない。
- `取得方法` は `AutoDriver` の結果で切り替わる。自動取得なら「ブラウザーのバージョンに
  合わせて自動取得」、`False` なら「固定パス（ブラウザー更新時は手動で入れ替え）」と出る。
  **ブラウザーだけ更新されて止まったときに、どちらの経路で動いていたかが後から分かる。**

### 起動したブラウザーが要求どおりか確かめる ★重要

**ドライバーは `browserName` の不一致を拒否する。** chromedriver に `MicrosoftEdge` を、
msedgedriver に `chrome` を渡すと、どちらも `session not created: No matching capabilities
found` を返した（実機確認）。ただし**バージョンの不一致は拒否しない** — msedgedriver 150 で
Edge 151 のセッションは作れた。

危ないのはフロー側の食い違いのほうである。`Browser` は capabilities のどのキーを読むかを
決め、`BrowserName` は WebDriver へ送る値で、片方だけ書き換えると**セッションは正常に
張れるのに版の取得だけが空振りする**。実機ではこれで「プロパティがありません」という、
原因とは無関係な行で止まった。応答の `browserName` を見て、`BrowserName` と違えば
そこで止める。

```
SET RealBrowser TO SessionObj['value']['capabilities']['browserName']
IF RealBrowser <> BrowserName THEN
    SET Halt TO True
    SET HaltReason TO $'''要求したブラウザー(%BrowserName%)と実際に起動したブラウザー(%RealBrowser%)が違います。ドライバーの取り違えです'''
END
```

**この判定を version の取得より前に置くこと。** `capabilities` の中でドライバーの版が入る
キーはブラウザーごとに違う（Chrome は `chrome.chromedriverVersion`、Edge は
`msedge.msedgedriverVersion`）ため、取り違えたまま先に進むと、こちらが想定したキーが
存在せず「プロパティがありません」で落ちる。原因（取り違え）とは無関係な行で止まるので、
切り分けが遠回りになる。

### 中止した理由を記録する

`Halt` は「ドライバー取得の失敗」「手動ログインのキャンセル」「起点画面に着けない」
「セットアップ中のエラー」のどれでも立つ。理由を持たせないと、最後のダイアログが常に
同じ文面になり、実際の原因と食い違う。`HaltReason` を必ずセットし、ダイアログと
ログの両方に出す。

```
[2026/08/02 16:20:11] 中止 繰り返しの起点画面に到達できませんでした
```



---

---

# 第 2 部　使い方

---

## 🤖 録画JSONファイルをPADコード(Robin)へ変換する

PAD のフローは内部的に **Robin 言語**で表現されており、フローデザイナーのキャンバスに
**Robin のテキストを貼り付ける（Ctrl+V）とアクションが並ぶ**。この性質を使い、
**Chrome等の DevTools Recorder でブラウザ操作を録画し JSONでエクスポートし バッチ定義 JSON 編集後に生成器で PAD のフローへ変換生成する**のがこの節の内容。

**アクションを 1 つずつ手で置く必要がない。**
それ以上に重要なのは、 **この手順書に書かれた落とし穴の回避策がすべて生成器に組み込まれている** 
ことで、`EncodeRequestBody: False` の指定漏れや
`SET` の右辺の `%` 誤用のような、貼り付けが黙って無視される類のミスを踏まなくなる。




### 🌐 変換の手段は 2 つ（出力は同じ）

| | 中身 | 向いている人 |
| --- | --- | --- |
| **ブラウザ版**（推奨） | `pad_converter.html` をブラウザーで開くだけ | 一般ユーザー向け。インストール不要、通信なし、Pythonなどの開発ツール不要 |
| Python 版 | `pad_webdriver_ref.py` をコマンドラインで実行 | 上級者向け。自動化したい人 |

**出力は 1 文字まで一致する。** `tools/verify_parity.mjs` が CI で毎回突き合わせている。
どちらで作ったものかは生成物のヘッダーに残る。

```
# 変換器：ブラウザ版 v1.0.0
```

版の値は両方にソース定数として持たせてあり、**上げるときは必ず同時に直す**。
`verify_parity.mjs` はこの 1 行だけ比較から外している（種類が必ず食い違うため）。


ブラウザ版の手順は 4 つ。

1. `tools/pad_converter.html` をダウンロードしてローカル（例 C:\Temp ）に置きブラウザーで開く
2. 録画 JSON をドラッグ＆ドロップ
3. **実行環境（PAD を動かす PC）のパス**を入力（明細ファイル / ドライバー / BaseDir）
4. 「変換する」→「Robin をコピー」→ PAD の**空の新規フロー**に `Ctrl+V`

引数を覚える必要がなく、画面に「実行環境のパスを入れる」と明記してあるので、
**変換環境のパスを渡してしまう取り違え**（後述）も起きにくい。

> 共通 JavaScript は**コピーのみ**で、保存機能は用意していない。実機で
> `pad_flow.jsact.js` がウイルス対策に誤ブロックされ、`.txt` にリネームしても
> 同じだった。**拡張子ではなく中身（DOM 操作のスクリプト）が誤検知される。**
> 同じ内容でも Robin 側は 18 行に分割されているため問題なくダウンロードできる。


<div align="center">
　ブラウザ版 生成器  `tools/pad_converter.html` の画面
  <img src="SS_pad_converter_html_1.png">
</div>




### 🗺️ 全体の流れ

```
┌───────────────────────────────────────────────────────────┐
│ 業務環境　操作録画環境（ブラウザの DevTools 使用） 　　　　　　│
│                                                           │
│  ① ブラウザ DevTools の Recorder で業務操作を録画           │
│           │  「JSON file」形式でエクスポート                │
│           ▼                                               │
│  ② recordings/<name>.json                                 │
│           │  setup / loop / recover / teardown に分割      │
│           │  値を {{列名}} / {{SECRET:…}} に置き換え        │
│           ▼                                               │
│  ③ バッチ定義 JSON 編集                                    │
│           │                                               │
└───────────▼───────────────────────────────────────────────┘
            │  
            │  操作録画ファイル（JSON）
            │  
┌─────────────────────────────────────────────────────────────┐
│ 変換生成器                                                   │
│           │  ブラウザ版 `pad_converter.html`                 │
│           │  　または                                        │
│           │  python版 `pad_webdriver_ref.py`                │
│           ▼                                                 │
│  ④ output/pad_flow.robin.txt   ← PAD に貼り付ける本体        │
│     output/pad_flow.jsact.js   ← 長い行が貼れない時に使う     │
│                                                             │
│   （任意）python版のみ --trace で手順書 pad_trace.md も出せる  │
└───────────┬─────────────────────────────────────────────────┘
            │  
            │  生成したPADコード(Robin) 
            │  
┌───────────▼────────────────────────────────────────────────────────────────────────────┐
│ 業務環境                                                                                │
│ （Power Automate Desktop 無料版(PAD) と WebDriver が使える PC。 Python は不要）           │
│                                                                                        │
│  ⑤ C:\temp に置く                                                                       │
│       msedgedriver.exe と selenium-manager-windows.exe ／ 明細CSV ／ pad_flow.jsact.js  │
│           ▼                                                                            │
│  ⑥ PAD で新規フロー → キャンバスに Ctrl+V                                                │
│           ▼                                                                            │
│  ⑦ MaxItems = 1 で試走 → 目で確認 → データ件数に増やし本番実行                             │
│           ▼                                                                            │
│  ⑧ C:\temp に出力                                                                       │
│       <ID>__<業務キー>__日時.png（エビデンス）                                           │
│       pad_result.csv（結果・再実行の入力にもなる）                                        │
│       pad_progress.log（進捗）                                                          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

**実行環境に Python が無くてもよい**のがこの方式の要点。
できあがった PADコード(Robin)を PAD に貼り付けて使う。

なお、録画（①）は**対象システムにアクセスできる環境**で行う必要がある。


---

### 手順 ①〜③：録画 JSON をバッチ定義 JSON にする

録画のしかたは README の「🎥 ブラウザに内蔵されている DevTools の Recorder でブラウザ操作録画 → 決定論リプレイ（拡張機能不要）」を参照。
エクスポートした JSON を、次の 4 つのセクションに振り分ける。

```
{
  "title":   "発注確認（注文受諾）",
  "setup":   [ …ログイン〜ループの起点まで（最初に 1 回だけ）… ],
  "loop":    [ …1 件分の手順（{{列名}} が明細の値で埋まる）… ],
  "recover": [ …失敗した次の件の前に、起点へ戻る最短手順… ],
  "teardown":[ …ログアウト等（任意・最後に 1 回だけ）… ]
}
```

#### いつ実行されるか

セクションの役割は「実行される回数とタイミング」で決まる。

```
setup      … 1 回だけ。ログインして、繰り返しの起点画面まで進む
  ↓
  ┌── loop ── 明細 1 行につき 1 回。ここが本体
  │     ↓ 失敗したら次の行の前に recover が入る
  └───────────
  ↓
teardown   … 1 回だけ。ログアウトなど（省略可）
```

`setup` の後に**起点画面かどうかの確認が自動で入る**。ループ最初の操作対象が
その画面にあるかを、クリックせずに調べる。無ければ明細を 1 件も処理せず中止する。
**この確認は生成器が作るので、自分で書く必要はない。**

#### セクションごとに使えるステップ種別

**書いても無視される組み合わせがある。** 生成器は対応していない種別を黙って捨てるので、
気づかないまま「エビデンスが保存されない」といった形で後から出る。
変換時に警告が出るようにしてあるので、必ず目を通すこと。

| 種別 | setup | loop | recover | teardown | 内容 |
| --- | :---: | :---: | :---: | :---: | --- |
| `comment` | ○ | ○ | ○ | ○ | 生成コードにコメントを残す |
| `setViewport` | ○ | − | − | − | ウィンドウサイズ。エビデンスに写る範囲が決まる |
| `navigate` | ○ | − | ○ | − | URL を開く |
| `click` / `doubleClick` | ○ | ○ | ○ | ○ | クリック |
| `change` | ○ | ○ | ○ | ○ | 入力欄に値を入れる |
| `screenshot` | − | ○ | − | − | エビデンスを保存する |
| `assertText` | − | ○ | − | − | 画面に文字列があるかを確認する |

**`loop` に `navigate` は置けない。** URL を開き直すと 1 件ごとにログイン画面へ
戻される作りのサイトがあるため、ループ内の移動は画面の操作（クリック）で行う。

**`setup` に `assertText` や `screenshot` は置けない。** 起点の確認は上記のとおり
自動生成されるので不要。

#### ステップの書き方

```json
{"type": "click", "selectors": [["aria/検索"], ["#SrchBtn"], ["text/検索"]]}
```

`selectors` は**候補の並び**。上から順に試し、最初に見つかったものを使う。
録画 JSON はこの形でエクスポートされるので、そのまま使えることが多い。
使える書式は `#id` / CSS セレクタ / `aria/ラベル` / `text/文字列` / `id/ID` / `xpath/式`。

```json
{"type": "change", "value": "{{発注番号}}", "selectors": [["#Value_0"], ["aria/発注番号"]]}
{"type": "screenshot", "name": "受諾完了"}
{"type": "assertText", "text": "発行しました"}
{"type": "comment", "text": "発注 {{発注番号}} の受諾を開始"}
{"type": "setViewport", "width": 1366, "height": 900}
```

#### 値の差し込み

| 書き方 | 置き換わるもの | 使える場所 |
| --- | --- | --- |
| `{{列名}}` | 明細 CSV のその列の値 | `value` / `text` / `name` / `url` / `selectors` の中 |
| `{{SECRET:名前}}` | ID・パスワード | `value` のみ |

セレクタの中でも使えるので、行を業務キーで特定できる。

```json
{"type": "click", "selectors": [["aria/{{発注番号}}"], ["id/N58:PosPoNumber:0"]]}
```

`{{SECRET:…}}` を置いた位置から、生成器が**ログイン部分の範囲を機械的に判定する**。
その範囲は「自動ログイン」ブロックに入り、既定では実行されない（手動ログインが既定）。
**生成物に資格情報は一切入らない。**

> **⚠️ 録画直後の JSON には入力した実値がそのまま残る。** 保存・コミット・共有の前に
> 必ず `{{SECRET:…}}` へ置き換えること。

#### 振り分けで押さえる 3 点

**`loop` の始点と終点を同じ画面にそろえる。** 1 件の最後に「ホームへ戻る」等を入れておけば、
次の件が必ず同じ状態から始まる。これが崩れると 2 件目以降の失敗理由が
「要素が見つからない」ばかりになって原因が追えない。

**`recover` を必ず書く。** 生成器は `recover` を「失敗した次の件の前に実行する復帰処理」として
使う。省略すると開始 URL を開き直すフォールバックになり、ログインが必要なサイトでは
セッションが切れる。`recover` が無いと **1 件の失敗が全件に連鎖する**。
中身は `setup` の末尾（起点へ向かう部分）と同じになることが多い。

**`loop` の最後の手前に `screenshot` を置く。** 完了画面が出ている状態で撮る。
ホームへ戻ってから撮っても、証跡として意味のあるものにならない。

#### 明細 CSV との対応

`{{列名}}` は明細 CSV の見出しと突き合わせる。`--id-column` で指定した列が `Col1` になり、
進捗ログ・結果 CSV・エビデンスのファイル名のキーになる。

```
プロジェクト番号,発注番号,skip
PM9000000001,900000000001,
PM9000000002,900000000002,1     ← skip 列に値があるとこの行は飛ばす
```

`skip` 列は任意。値が入っている行は処理せず「スキップ」として記録される。

---

### 手順 ④：PADコード(Robin)を生成する
#### 一般ユーザー向け: ブラウザ版 `pad_converter.html`　　※ Python などの開発ツール不要

<div align="center"> <img src="SS_pad_converter_html_2.png"> </div>

1. 録画 JSON
ここにドラッグ＆ドロップ、またはファイルを選択

2. 実行環境（PAD を動かす PC）のパス
ここに書いた値は生成物にそのまま埋め込まれます。変換した PC のパスではなく、 PAD を動かす PC のパスを入れてください。
明細ファイル (--details)：   C:\temp\edi2_batch.csv
ID 列 (--id-column)： 　プロジェクト番号
　　　　下の「明細ファイル」を選べば先頭列が自動で入ります
ドライバー (--driver-exe)：　C:\temp\msedgedriver.exe
BaseDir (--pad-out-dir)：  C:\temp

3. オプション
ブラウザー (--pad-browser)：  edge
プロキシ (--proxy) ： 　proxy.example.com:8080
ドライバー自動取得：   --auto-driver
明細ファイル（列名の確認用・任意） ファイルが選択されていません
上の「明細ファイル (--details)」は実行環境のパスを書くだけで、中身は読めません。 
列名を確かめたい場合は、変換するこの PC にある同じ CSV をここで選びます。



#### 上級者向け: Python版の変換器 `pad_webdriver_ref.py`
```
# Python版の変換器を使う場合は Python必要。（ブラウザ、WebDriver は不要）
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json `
    --details "C:\temp\edi2_batch.csv" --id-column "プロジェクト番号" `
    --robin output/pad_flow.robin.txt `
    --driver-exe "C:\temp\msedgedriver.exe" --pad-out-dir "C:\temp"
```

**引数のパスは 2 種類あるので混ぜないこと。**

| 引数 | どのマシンのパスか |
| --- | --- |
| `--batch` / `--robin` | **変換環境**（Python が使える PC）のパス。リポジトリ相対でよい |
| `--details` / `--driver-exe` / `--pad-out-dir` | **実行環境**（PAD を動かす PC）のパス。生成された Robin に文字列として埋め込まれる |

| 引数 | 役割 |
| --- | --- |
| `--batch` | バッチ定義 JSON（③で作ったもの） |
| `--details` | 明細 CSV のパス。`SET DetailsFile` になる |
| `--id-column` | ID 列の名前。この列が `Col1` になり、進捗・結果・再実行のキーになる |
| `--robin` | 出力先。同名で `.jsact.js` も一緒に出る（ブラウザ版はコピーのみ） |
| `--driver-exe` | `msedgedriver.exe` のパス。`SET DriverExe` になる |
| `--pad-out-dir` | 出力フォルダ。`SET BaseDir` になる |

`--details` と `--driver-exe` が `--pad-out-dir` の配下にある場合、生成される Robin は
それらを `%BaseDir%` 相対で出力する。上の例なら次のようになり、**配布時に直すのは
`BaseDir` の 1 行だけ**で済む。

```
SET BaseDir TO $'''C:\\temp'''
SET DriverExe TO $'''%BaseDir%\\msedgedriver.exe'''
SET DetailsFile TO $'''%BaseDir%\\edi2_batch.csv'''
SET ResultFile TO $'''%BaseDir%\\pad_result.csv'''
SET LogFile TO $'''%BaseDir%\\pad_progress.log'''
SET ShotDir TO $'''%BaseDir%'''
```

配下でないパスを渡した場合は絶対パスのまま出力されるので、環境ごとに 3 行を直すことになる。



#### 生成器が自動で行う変換

| 録画 JSON | 生成される PADコード(Robin) |
| --- | --- |
| `{{列名}}` | ループ先頭で `SET Col1 TO Row['列名']` として取り出し、以降は `%Col1%` で参照 |
| `{{SECRET:…USER…}}` / `{{SECRET:…}}` | `%IdSafe%` / `%PwSafe%`（JSON 用にエスケープ済みの変数） |
| `xpath///*[@id="X"]` | `id/X`（リテラルに引用符を持ち込まないため） |
| 単引用符を含むセレクタ候補 | 生成時に除外（貼り付けが無視されるため） |
| 共通 JavaScript | 1 行 100 文字程度に分割して `SET JsAct TO $'''%JsAct%…'''` で継ぎ足し |

**`%Row['列名']%` を直接使わないのが要点。** リテラル内に単引用符が入ると PAD が
貼り付けを無視するため、ループ先頭で変数へ取り出す形に変換している。

#### 生成される制御構造

録画には含まれない運用機能が自動で付く。すべて手順書の該当節と同じ実装。
**PAD標準の録画機能は単純に操作をアクションにしていくだけだが、この生成器は自動でバッチ運用に必要な要素や、はまりどころの回避策を反映してくれる。**

- **手動ログイン（既定）** … `LoginMode = manual`。人が手でログインし、PAD はパスワードを
  一度も受け取らない。録画されたログイン手順は `IF LoginMode = auto THEN` の中に入る
- **セットアップ失敗の検知** … `Halt` が立つと明細を 1 件も流さずに中止する
- **件数制限** … `MaxItems`。打ち切った行は「未実行」として結果に残る
- **skip 列** … 値がある行は飛ばす
- **失敗分の再実行** … `RetryMode = True` で結果 CSV を明細として読み直す
- **失敗後の復帰** … `PrevFailed` を悲観的に立て、次の件の前に `recover` を実行する
- **エビデンス** … WebDriver の `/screenshot`（ブラウザのページだけが写る）＋日時つき命名
- **失敗時エビデンス** … `fail__` 接頭辞で保存する
- **結果 CSV と進捗ログ** … 成功・失敗・スキップ・未実行を 1 行ずつ記録

#### 生成時の自動チェック

書き出しの直前に、実機で判明している落とし穴を機械的に洗って警告する。
**PAD は解釈できない行をエラーも出さずに無視する**ため、生成時に気づけないと
「貼り付けたのにアクションが足りない」という形で後から発覚する。

- 700 文字を超える行
- `SET x TO %y%` … 変数の代入で `%` を使っている
- `EncodeRequestBody: False` の欠落
- リテラル内のエスケープされていない単引用符

**警告が出たら貼り付ける前に直すこと。** 何も出なければそのまま進んでよい。

---

### 手順 ⑤：実行環境にファイルを置く

`C:\temp`（= `--pad-out-dir` に指定した場所）に次を置く。

| ファイル | 用途 |
| --- | --- |
| `msedgedriver.exe` | Edge と**同じメジャーバージョン**のもの |
| 明細 CSV | `--details` で指定した名前。1 行目が列名 |
| `pad_flow.jsact.js` | 共通 JavaScript。継ぎ足しが通れば使わないが、保険として置く |

`localhost` / `127.0.0.1` がプロキシ除外に入っていることも確認する。

---

### 手順 ⑥：Power Automate Desktop 無料版(PAD) に貼り付ける

1. PAD で新しいデスクトップフローを作る（⚠️**Power Fx は有効にしない**）
2. `pad_flow.robin.txt` をテキストエディタで開き、**全選択してコピー**
3. フローデザイナーのキャンバスをクリックしてから **Ctrl+V** で貼り付ける

**アクションが並べば成功。** 何も起きない、または一部しか並ばない場合は、
「Robin リテラルのエスケープ」の節の切り分け手順を使う。要点は 2 つ。

- **4 ブロックに分けて貼る**（設定〜セッション開始／セットアップ／ループ／後片付け）と
  どこで弾かれているか特定できる
- **弾かれた行のアクション名が PAD のバージョンと違う可能性が高い。** PAD で同じアクションを
  1 つキャンバスに置いてコピー（Ctrl+C）してテキストに貼れば、その環境での正しい書式が分かる

`SET JsAct TO …` の継ぎ足しが通らなかった場合だけ、その行を削除して
「変数の設定」アクションを 1 つ置き、値の欄に共通 JavaScript の中身を直接貼る
（UI の入力欄なら長い文字列でも入る）。変数名は `JsAct`。中身はブラウザ版の
「共通 JavaScript をコピー」か、Python 版が出力する `pad_flow.jsact.js` から取る。

---

### 手順 ⑦：試走から本番へ

**⚠️いきなり全件流さない。** 生成時の既定は `MaxItems = 1` になっている。

| 回 | 設定 | 確認すること |
| --- | --- | --- |
| 1 回目 | `MaxItems = 1` | ブラウザが起動する／ログインできる／1 件が「成功」になる／エビデンスが開ける |
| 2 回目 | `MaxItems = 10` | 2 件目以降も通る／skip 行が飛ぶ／結果 CSV の列がずれない |
| 3 回目 | 失敗を仕込む | `fail__` の PNG が実体としてできる／次の件が復帰して成功する |

3 回目が**いちばん省略されやすく、いちばん重要**。成功経路だけ確認して配布すると、
最初の失敗が起きたときに証跡が無いことに気づく。やり方は「失敗経路の検証方法」の節に書いた。

---

### 手順 ⑧：出力を確認する

| 出力 | 内容 |
| --- | --- |
| `<ID>__<業務キー>__yyyyMMdd_HHmmss.png` | 成功時のエビデンス |
| `fail__<ID>__<業務キー>__yyyyMMdd_HHmmss.png` | 失敗時の画面 |
| `pad_result.csv` | ID・業務キー・結果・理由・エビデンス・実行日時 |
| `pad_progress.log` | 実行開始の区切り行、ドライバー確認の 1 行、1 件ごとの開始・成功・失敗、中止理由 |

`pad_result.csv` は**そのまま明細として読み直せる列構成**にしてある。失敗分と、件数上限で
打ち切った未実行分を流し直すには `RetryMode` を `True` にするだけ。

進捗ログは**中止したときも必ず 1 行以上残る**。実行開始のヘッダーはドライバーを触る前に
書いており、中止時は理由も書く。ログ書き込みをループの中だけに置くと、起点画面に着けずに
中止したとき「ログを確認してください」と案内しながらログが空、という状態になる。

> **⚠️ 登録系の再実行は二重登録に注意。** 再実行の前に `fail__` の画像で実際の画面を
> 確認すること。

---

### （任意）手順書だけを出す　　　※ Python版のみ

`--robin` の代わりに `--trace` を使うと、**PAD が送るのと同じ HTTP 呼び出しを同じ順序で
実際に送りながら**、その呼び出し列を Markdown の表として書き出せる。フローを人に説明する
資料や、生成物が期待どおりか確かめる用途に使う。

```
# 別ターミナルでWebドライバーを実行しておく: msedgedriver.exe --port=9515
# 手順書生成
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json `
    --details data/edi2_practice_batch.csv --trace output/pad_trace.md
```

「何番目に・どのメソッドで・どの URL へ・どんな本文を送るか」が全件出力される
（セッション ID は `{session}` に伏せ、秘密情報は `[SECRET:名前]` の表記で残らない）。

---

### フローが増えたときの進め方

**2 本目以降はバッチ定義 JSON を差し替えるだけ。** 生成器・手順書・落とし穴の対処は
共通なので、1 本目で通った環境なら 2 本目は録画からフロー完成までが一気に進む。

ただし**フロー間で規約をそろえること。** 特に `--id-column` に何を指定するか、
結果 CSV の列構成、エビデンスの命名は、フロー 1 と 2 で違うと運用側が混乱する。

---

# 第 3 部　運用

---

## 🔐 資格情報の扱い

### 推奨：手動ログイン

**Key Vault 連携の資格情報機能はプレミアム機能である。** 無料版で最も安全なのは、フローが
ブラウザーを開いたところで一旦止め、**人が手でログインする 手動ログイン方式。**

```
Display.ShowMessageDialog.ShowMessage Title: $'''手動ログイン''' Message: $'''いま開いたブラウザーでログインし、繰り返しの起点画面まで進んでから[OK]を押してください。ブラウザーは閉じないでください。''' Icon: Display.Icon.Information Buttons: Display.Buttons.OKCancel DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> LoginBtn
IF LoginBtn = $'''Cancel''' THEN
    SET Halt TO True
END
```

**ログインだけでなく、繰り返しの起点画面まで人が進める。** ログイン直後の画面構成（ナビゲータの
展開順など）はサイト側の都合で変わることがあり、録画どおりに機械的に辿らせると起点に着けず
セットアップ失敗で止まる。実サイトでまさにこれが起きた。人が起点まで進めばその差異に影響されず、
録画のログイン以降の手順は `LoginMode` が `auto` のときだけ実行すればよい。

**手動ログイン方式は PAD がパスワードを一度も受け取らない安全設計。** 変数ペイン・実行ログ・エラーメッセージのどこにも
残りようがない。パスワードを扱うコードがフローに存在しないこと自体が、運用上の安全になる。
数十件程度ならこれで足りる。

> WebDriver は**自分が起動したブラウザーしか操作できない。** 別に開いてある普段のブラウザーで
> ログインしても、フローはそのタブを見られない。

自動ログインへ切り替えるときの注意点は [自動ログインへの設計変更](PAD_WebDriver_internals.md#-自動ログインへの設計変更) を参照。

---

## 📊 結果 CSV と再実行

列構成は、**その CSV をそのまま明細として読み直せる形**にする。

```
プロジェクト番号,発注番号,結果,理由,エビデンス,実行日時
```

ID だけでなく**業務キー（例では発注番号）も必ず含める**。これが無いと再実行時に対象を特定できない。

再実行はモードフラグ 1 つで実現できる。

```
SET RetryMode TO False
IF RetryMode THEN
    SET DetailsFile TO $'''%BaseDir%\\pad_result.csv'''
    SET ResultFile TO $'''%BaseDir%\\pad_result_retry.csv'''
END
```

ループ先頭で結果列を見て絞る。

```
IF RetryMode THEN
    SET DoRow TO False
    IF Row['結果'] = $'''失敗''' THEN
        SET DoRow TO True
    END
    IF Row['結果'] = $'''未実行''' THEN
        SET DoRow TO True
    END
    IF DoRow = False THEN
        NEXT LOOP
    END
END
```

**対象は「失敗」だけでなく「未実行」も含める。** `MaxItems` で打ち切った行は「未実行」で
記録されるため、失敗だけを拾う条件にすると、上限を小刻みにして回す運用で続きが流せない。
`AND` を使わず IF を並べているのは、複合条件の書式が実機で未検証のため。

**出力先は必ず別名にする。** 同じファイルを読みながら書くと壊れる。再実行 CSV には `skip` 列が
無いので、`skip` の判定は `IF RetryMode = False THEN` で囲む。

進捗ログには**失敗も書く**こと。失敗を結果 CSV にだけ書いていると、ログには「開始」だけが残り、
「成功が出ていない」ことから推測させる形になる。

> **⚠️ 登録系の再実行は二重登録に注意。**「実は登録は成功していたが確認段階で失敗扱いになった」
> ことがある。再実行の前に失敗時のエビデンスで実際の画面を確認すること。

---

---

## 📸 エビデンス（スクリーンショット）

### ウィンドウサイズ

エビデンスに写る範囲はウィンドウサイズで決まる。**複数の PC に配布する場合は、一番小さい画面に
収まるサイズにそろえる。** 大きすぎる値を指定すると OS 側でクランプされ、環境によって写る範囲が
変わってしまう。解像度がまちまちなら `POST …/window/maximize` を使う手もあるが、
その場合はエビデンスの画像サイズが PC ごとに変わる。

一般的な画面の例
| **名称** | **横×縦** |
| --- | --- |
| **VGA** | **640×480** |
| **SD(SDTV)** | **720×480** |
| WVGA(Wide-VGA) | 800×480 |
| SVGA(Super-VGA) | 800×600 |
| WSVGA(Wide-SVGA) | 1024×600 |
| **XGA** | **1024×768** |
| WXGA(Wide-XGA) | 1280×800 |
| Quad-VGA | 1280x960 |
| **HD** | **1440×1080** |
| SXGA(Super-XGA) | 1280×1024 |
| SXGA+ | 1400×1050 |
| WSXGA (Wide-SXGA) | 1600×1024 |
| WSXGA+ (Wide-SXGA+) | 1680×1050 |
| UXGA (Ultra-XGA) | 1600×1200 |
| **FHD/2K** | **1920×1080** |
| WUXGA (Wide-UXGA) | 1920×1200 |
| QWXGA (Quad-Wide-XGA) | 2048×1152 |
| QXGA (Quad-XGA) | 2048×1536 |
| WQHD (Wide-Quad-HD) | 2560×1440 |
| **UHD/4K** | **3840×2160** |

---

撮り方の実装（PAD の標準アクションを使わない理由、列挙型の落とし穴）は [PAD_WebDriver_internals.md](PAD_WebDriver_internals.md) を参照。

---

## 📥 ファイルのダウンロード（エビデンスが画面に出ない場合）

登録の結果が画面に表示されず、**別メニューから Excel や PDF をダウンロードして初めて
内容が分かる**業務がある。スクリーンショットでは証跡にならないため、ファイルとして
受け取って保存する必要がある。以下はすべて実機で確認した書式（PAD 無料版 / Windows 11 / Edge）。

### 保存先を固定し、確認ダイアログを出さない

WebDriver が起動するブラウザーは素のプロファイルなので、既定では「ダウンロード」
フォルダーに落ち、場合によっては確認が出る。セッション作成時の `prefs` で 4 つとも抑える。

```
SET SessionBody TO $'''%SessionBody%, \"ms:edgeOptions\": {\"prefs\": {\"download.default_directory\": \"C:\\\\temp\\\\evidence\"'''
SET SessionBody TO $'''%SessionBody%, \"download.prompt_for_download\": false, \"plugins.always_open_pdf_externally\": true'''
SET SessionBody TO $'''%SessionBody%, \"profile\": {\"default_content_setting_values\": {\"automatic_downloads\": 1}}}}'''
```

| 設定 | 効果 |
| --- | --- |
| `download.default_directory` | 保存先。**JSON の中に Windows パスを書くのでバックスラッシュは 4 本**（Robin で `\\`→`\`、JSON で `\\`→`\`） |
| `download.prompt_for_download: false` | 保存ダイアログを出さない |
| `plugins.always_open_pdf_externally: true` | **PDF をビューアで開かずファイルとして落とす。** これが無いと PDF は保存されない |
| `automatic_downloads: 1` | 「複数ファイルのダウンロードを許可しますか」を出さない |

**`prompt_for_download` と `automatic_downloads` は別物。** 前者だけでは
「ブロック / 許可」の確認が出て、押すまでダウンロードが始まらない。

### 完了を待つ

クリックした瞬間はまだ書き込み中で、`.crdownload` が残る。**それが消えたことだけを
見ていると、ダウンロードが始まる前に条件を満たして先へ進んでしまう。** 目的のファイルが
実際に現れるまで数える。

```
LOOP WHILE Pending > 0
    Folder.GetFiles Folder: DlDir FileFilter: $'''*.crdownload''' IncludeSubfolders: False FailOnAccessDenied: True SortBy1: Folder.SortBy.Name SortDescending1: False SortBy2: Folder.SortBy.LastModified SortDescending2: False SortBy3: Folder.SortBy.LastAccessed SortDescending3: False Files=> TempFiles
    SET Pending TO TempFiles.Count
    …（目的のファイルがそろったか数え、そろっていなければ Pending を 1 に戻す）
    WAIT 1
    SET Waited TO Waited + 1
    IF Waited >= 30 THEN
        SET Pending TO 0
    END
END
```

複合条件（`AND`）は実機未確認なので使わず、打ち切りは内側の `IF` で行っている。

### エビデンス名に付け替える

```
File.RenameFiles.Rename Files: SrcFile NewName: NewBase KeepExtension: True IfFileExists: File.IfExists.Overwrite RenamedFiles=> RenamedFiles
```

- **`NewName` は拡張子なしの名前だけでよい。** `KeepExtension: True` なので元の拡張子が残り、
  **Excel と PDF で処理を分ける必要がない**
- リネームは同じフォルダー内で行われるため、パスを付ける必要はない
- **対象が存在しないと `FileNotFoundException` で止まる。** `Folder.GetFiles` で
  存在を確かめてから実行すること

サーバーが付けるファイル名が事前に分からない場合は、クリック前にファイル数を数え、
増えたあとで `Folder.SortBy.LastModified` の降順から一番新しいものを取る。

### 落とし穴

- **ドライバーを取り違えてもセッションは張れる場合がある**が、`browserName` の不一致は
  chromedriver も msedgedriver も `session not created` で拒否する。一方
  **バージョンの不一致は拒否しない**（msedgedriver 150 で Edge 151 のセッションが張れた）
- **単体のスクリプトファイルはウイルス対策に誤ブロックされる。** `.js` でも `.txt` でも同じで、
  拡張子ではなく中身が検知される。共通 JavaScript はコピーで受け渡すこと

---

## 🕒 日時とファイル名

`DateTime.DateTimeFormat.DateAndTime` は `2026/07/23 8:41:00` のような値を返し、`/` と `:` は
Windows のファイル名に使えない。テキストに整形してから使う。

```
DateTime.GetCurrentDateTime.Local DateTimeFormat: DateTime.DateTimeFormat.DateAndTime CurrentDateTime=> NowDt
Text.ConvertDateTimeToText.FromCustomDateTime DateTime: NowDt CustomFormat: $'''yyyyMMdd_HHmmss''' Result=> Stamp
```

**`MM` は月、`mm` は分。** `yyyymmdd` と書くと月の位置に分が入る。

ファイル名は「ID ＋業務キー＋日時」で一意にする。失敗時は接頭辞を付けると探しやすい。

```
<ID>__<業務キー>__yyyyMMdd_HHmmss.png
fail__<ID>__<業務キー>__yyyyMMdd_HHmmss.png
```

出力フォルダの変数（`BaseDir` / `OutDir`）**末尾に `\` を付けないこと**（パスが二重区切りになる）。

---

---

# 第 4 部　練習

---

## 🧪 実環境が無くても練習できる

同梱の練習サイト `test_site/edi2/index.html` は、実 EBS と同じ要素 ID
（`#usernameField` / `#POS_ORDERS` / `#SrchBtn` / `#Value_0` / `#ActionGoBtn` / `#PosSubmitBtn` /
検索結果リンク `#N58:PosPoNumber:0`）で発注確認の流れを再現している。
**単一ファイルなので Python のサーバーは不要** — `file:///…/test_site/edi2/index.html` で開けば動く。

ログインは `demo` / `password123`。この練習サイトでフローを完成させてから、URL と資格情報だけを
本番向けに差し替えるのが安全な進め方。

> **練習サイトの限界。** この練習サイトは**存在しない発注番号でも受け付けて確認完了まで通る。**
> 検索ヒット 0 件の状態を再現できないため、「該当データが無い」という実務で最も多い失敗を
> サイト側では起こせない。失敗経路の検証には
> [`examples/pad/sample.html`](../examples/pad/sample.html) を使うか、フローに一時的な
> 意図的失敗を仕込む（下記）。

### 失敗経路の検証方法

成功経路が通っても、**失敗経路は一度も動いていない。** 本番で価値を持つのはむしろこちらなので、
配布前に一度は通しておく。

セレクタを壊すと全件が失敗して復帰の確認ができないため、**行によって結果が変わる仕掛け**を
一時的に入れる。挿入場所は**エビデンス保存の直前**（＝登録が完了し、起点ではない画面にいる状態）。

```
# ★テスト用（確認後に削除する）
IF Col2 = $'''<テスト用の業務キー>''' THEN
    SET RowError TO $'''テスト用の意図的な失敗（発行後）'''
    …既存の失敗ブロックと同じ処理…
    NEXT LOOP
END
```

明細は「失敗させる行 → 正常な行」の順に並べる。**2 行目が成功すれば復帰処理が効いている。**
これは「登録は成功したが確認段階で失敗と記録された」という、二重登録の危険が生まれる状況
そのものなので、一度実際に発生させておく意味がある。


---

---

## 📦 サンプル

[`examples/pad/`](../examples/pad/) に、社内固有の情報を含まない**公開用の動くサンプル**を用意した。

| ファイル | 内容 |
| --- | --- |
| `sample.html` | ログイン → 検索 → 明細 → 確認 の 4 画面を持つデモページ（単一ファイル） |
| `sample_batch.csv` | 明細（`ID,KEY,skip` の 3 列） |
| `pad_sample_batch.json` | バッチ定義（このファイルから Robin を生成する） |
| `pad_sample.robin.txt` | PAD に貼り付けるフロー（生成物） |
| `pad_sample.jsact.js` | 共通 JavaScript（`%JsAct%` の継ぎ足しが失敗したとき手で貼る用） |

`sample.html` / `sample_batch.csv` / `pad_sample.jsact.js` を `C:\temp\` に置き、
`msedgedriver.exe`（と `--auto-driver` を使うなら `selenium-manager-windows.exe`）を
同じ場所に用意してから、`pad_sample.robin.txt` を PAD のキャンバスに貼り付けて実行する。

`pad_sample.robin.txt` は手で保守せず、生成器から作り直す。

```
python pad_webdriver_ref.py \
  --batch examples/pad/pad_sample_batch.json \
  --details "C:\temp\sample_batch.csv" --id-column ID \
  --robin examples/pad/pad_sample.robin.txt \
  --driver-exe "C:\temp\msedgedriver.exe" \
  --pad-out-dir "C:\temp" --pad-browser edge --auto-driver
```

付属の `sample_batch.csv` は、**1 回の実行で成功・失敗・復帰・スキップの 4 経路すべてを通る**
並びになっている。

| 行 | キー | 結果 |
| --- | --- | --- |
| DEMO-001 | K-1001 | 成功 |
| DEMO-002 | K-9999 | 失敗（存在しないキー → 検索 0 件） |
| DEMO-003 | K-1002 | **復帰して成功**（ここが成功すれば復帰処理が効いている） |
| DEMO-004 | K-1003 | スキップ |

`sample.html` は有効キーを 3 つに限定してあり、それ以外は「No records found」で
検索結果の行自体を生成しない。練習サイトで再現できない「検索 0 件」を、こちらでは
意図的に作れるようにしている。


---

---

# 第 5 部　困ったとき

---

## ❓ うまくいかないとき

- **社外サイトが真っ白になる** … WebDriver のブラウザーはシステムのプロキシを引き継がない。
  「社外サイトへ出る」の節を参照し、`UseProxy` を `True` にする。

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| ①で接続できない | ドライバーが起動していない / プロキシ | ポート 9515、プロキシ除外に `localhost` |
| `session not created` | Edge とドライバのバージョン不一致 / 古いドライバがポートを占有 | ドライバを入れ替える / 起動前にプロセス終了 |
| `invalid argument: missing command parameters` | 本文が URL エンコードされている | **`EncodeRequestBody: False`** |
| `無効な URI: URスキームが有効ではありません` | `Url:` に本文用の変数を渡している | URL 用の変数を渡す |
| `パラメーター 値:変数 X が存在しません` | 変数名の誤り、または未初期化 | 変数名を確認 |
| 貼り付けても何も起きない | 1 行が長すぎる / `'` が未エスケープ | 行を分割する / `\'` にする |
| 変数が展開されない | `\%` と書いている | `%` にする |
| ファイルパスが二重区切りになる | フォルダ変数の末尾に `\` | 末尾の `\` を外す |
| ④が `ok:false` | セレクタが古い | F12 で確認して候補を足す / 画面遷移直後なら待機を入れる |
| 検索 0 件なのに次へ進む | 隠れている要素をクリックしている | 可視判定を足す / `exists` で確認 |
| 画面遷移が間に合わない | 待機不足 | ④の前に 1〜2 秒待つか、`exists` で目的の文字が出るまで待つ |
| スクショが全画面 | PAD の標準アクションは全画面固定 | WebDriver の `/screenshot` を使う |
| PNG ができないのにエラーも出ない | `IfExists.DoNothing` で静かに通過 | 実体を目で確認する |
| 1 件失敗したら以降も全部失敗 | 失敗した画面のまま次の件を始めている | 復帰処理を入れる |
| 全件が「ステップ 1 で失敗」 | セットアップ（ログイン）が失敗している | セットアップ失敗の検知を入れる |
| ファイル名の月が変な数字 | `yyyymmdd` と書いた（`mm` は分） | `yyyyMMdd` |
| 実行後もブラウザが残る | 後片付けを通っていない | ⑥の DELETE と `System.TerminateProcess` を最後に必ず通す |

---

---

## ⚠️ 制約

- **`iframe` 内の要素には届かない。** 別途 `/frame` への切り替えが必要
- Power Fx を有効にしたフローでは書式が変わる（1 起点のインデックス、厳格な型システム、
  データテーブルとカスタムオブジェクトが型なし扱いになりキャストが必要）。
  **既存フローの後付け有効化はできない**ため、移行するなら作り直しになる

---

---

## 🧩 仕組みを知りたいとき

生成器がどう作られているか、実機で分かった PAD の癖は
[PAD_WebDriver_internals.md](PAD_WebDriver_internals.md) にまとめてある。

- 使う HTTP 呼び出しは 6 種類だけ
- 共通 JavaScript（DOM ベース要素インデックス方式）
- 生成されるフローの組み立て
- `Web.InvokeWebService` の引数、Robin リテラルのエスケープ
- 実機で確認できた書式 / 無効だった構文
