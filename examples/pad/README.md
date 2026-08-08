# PAD WebDriver サンプル

社内固有の情報を含まない、そのまま動くサンプル一式。

| ファイル | 内容 |
| --- | --- |
| `sample.html` | ログイン → 検索 → 明細 → 確認 の 4 画面を持つデモページ（単一ファイル） |
| `sample_batch.csv` | 明細（`ID,KEY,skip` の 3 列） |
| `pad_sample_batch.json` | バッチ定義。ここから Robin を生成する |
| `pad_sample.robin.txt` | PAD に貼り付けるフロー（生成物・手で直さない） |
| `pad_sample.jsact.js` | 共通 JavaScript。`%JsAct%` の継ぎ足しが失敗したとき手で貼る用 |

## 改行コード

`examples/pad/` の配布物は `.gitattributes` で **CRLF に固定**してある。PAD も
`File.ReadFromCSVFile.ReadCSV` も Windows 向けで、LF のまま渡すと取り込みに失敗する
ことがあるため。ZIP ダウンロードやコピー＆ペーストで持ってきた場合は、`sample_batch.csv`
の改行が CRLF になっているか確認する。

```powershell
$p = "C:\temp\sample_batch.csv"
$t = [IO.File]::ReadAllText($p) -replace "`r`n", "`n" -replace "`n", "`r`n"
[IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $false))
```

## 実行の準備

1. `sample.html` / `sample_batch.csv` / `pad_sample.jsact.js` を `C:\temp\` にコピー
2. `msedgedriver.exe`（Edge と同じメジャーバージョン）を `C:\temp\` に置く
   `--auto-driver` を使う場合は `selenium-manager-windows.exe` も同じ場所に置く
3. `127.0.0.1` / `localhost` をプロキシ除外に入れる
4. PAD で**新規フロー**を作り（Power Fx は無効）、`pad_sample.robin.txt` を
   キャンバスに `Ctrl+V` で貼り付ける

貼り付け先は必ず空のフローにすること。既存のアクションが残っていると、
うまく動かなかったときに原因の切り分けができなくなる。

## このサンプルで通る経路

`sample_batch.csv` は、**1 回の実行で成功・失敗・復帰・スキップの 4 経路すべてを通る**並び。

| 行 | キー | 結果 |
| --- | --- | --- |
| DEMO-001 | K-1001 | 成功 |
| DEMO-002 | K-9999 | 失敗（存在しないキー → 検索 0 件） |
| DEMO-003 | K-1002 | **復帰して成功**（ここが成功すれば復帰処理が効いている） |
| DEMO-004 | K-1003 | スキップ |

`MaxItems` の既定は 1 なので、4 経路を通すには生成物の `SET MaxItems TO 1` を
`4` に変えるか、`--max-items 4` を付けて生成し直す。

## 作り直しかた

`pad_sample.robin.txt` は手で保守しない。生成器から作り直す。

```
python pad_webdriver_ref.py \
  --batch examples/pad/pad_sample_batch.json \
  --details "C:\temp\sample_batch.csv" --id-column ID \
  --robin examples/pad/pad_sample.robin.txt \
  --driver-exe "C:\temp\msedgedriver.exe" \
  --pad-out-dir "C:\temp" --pad-browser edge --auto-driver
```

**`--details` は実行環境（PAD を動かす PC）のパスを渡すこと。** ここに変換環境の
リポジトリ相対パスを書くと、生成物に `SET DetailsFile TO $'''examples/pad/sample_batch.csv'''`
がそのまま埋め込まれ、実行時に「CSVファイルから読み取る」で失敗する。
`--batch` と `--robin` は変換環境のパス。

詳しい解説は [`../../docs/PAD_WebDriver.md`](../../docs/PAD_WebDriver.md)。
生成器の設計は [`../../docs/PAD_WebDriver_internals.md`](../../docs/PAD_WebDriver_internals.md)。
