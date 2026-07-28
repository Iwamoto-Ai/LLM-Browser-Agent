# Copyright 2026 Iwamoto-Ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Power Automate Desktop（PAD）版バッチの**参照実装**。

PAD には Web 自動化用のブラウザ拡張機能が必要だが、**WebDriver は拡張とは無関係**で、
`msedgedriver.exe` 自体がローカルの HTTP サーバーとして動く。したがって
「HTTP リクエストを送れるツール」があれば拡張なしでブラウザを操作できる。
PAD の「Web サービスの呼び出し」がまさにそれに当たる。

このスクリプトは **PAD が送るのと同じ HTTP 呼び出しを、同じ順序で送る**ことだけを行う
（Selenium も Playwright も使わず、Python 標準ライブラリの urllib のみ）。自宅で本スクリプトを
練習サイトに対して流して成功を確認し、`--trace` で出力される「HTTP 呼び出しの実物」を
そのまま PAD のフローに書き写す、という使い方を想定している。

設計上の要点:
  * 要素の特定と操作は **`/execute/sync`（JavaScript 実行）に一本化**する。
    W3C 標準の「要素を検索して要素 ID を得る → その ID を操作する」方式は往復が増え、
    `element-6066-11e4-a52e-4f735466cecf` という長いキーの取り回しが PAD では煩雑なため。
    結果として PAD 側は**同じ形の HTTP 呼び出し 1 種類**を用意し、送る引数を変えるだけで済む。
  * セレクタは既存の録画 JSON の候補リストをそのまま使える（css / xpath/ / text/ / aria/ / pierce/）。
    候補は JS 側で順に試し、最初に見つかったものを操作する。

使い方（例）:
  # 1) 別ターミナルで WebDriver を起動しておく
  #    msedgedriver.exe --port=9515
  # 2) 練習サイトに対してバッチを流し、PAD 用の手順書を出力する
  python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json \
      --details data/edi2_practice_batch.csv --trace output/pad_trace.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

from engine_common import mask_secrets, resolve_secrets
from recorder_import import fill_value, load_recording
from run_batch import load_details

# ---------------------------------------------------------------------------
# 要素の特定と操作をまとめて行う JavaScript。
# 引数: arguments[0]=セレクタ候補の配列, arguments[1]=操作, arguments[2]=値
# 戻り値: {"ok": true/false, "used": 実際に一致したセレクタ}
# PAD へはこの文字列を 1 行にして貼り付ける（--trace の出力にそのまま含まれる）。
# ---------------------------------------------------------------------------
JS_ACT = r"""
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
"""


def js_act_oneline() -> str:
    """JS_ACT を 1 行にする（Robin の文字列リテラルや JSON へ安全に埋め込むため）。
    JS_ACT は二重引用符とバックスラッシュを含まない書き方に統一してあるので、
    JSON へ入れてもエスケープが発生せず、PAD 側でも壊れない。"""
    return " ".join(line.strip() for line in JS_ACT.strip().splitlines() if line.strip())


class WebDriverHTTP:
    """W3C WebDriver を HTTP で直接叩く最小クライアント（標準ライブラリのみ）。"""

    def __init__(self, base_url: str = "http://127.0.0.1:9515",
                 browser_name: str = "MicrosoftEdge", trace: list | None = None):
        self.base = base_url.rstrip("/")
        self.browser_name = browser_name
        self.session_id: str | None = None
        self.trace = trace if trace is not None else []

    # ---- 低レベル ---------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None,
              note: str = "", trace_body: dict | None = None):
        """trace_body を渡した場合は、記録にはそちら（秘密情報を含まない版）を残す。
        実際に送信するのは常に body。"""
        url = self.base + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json; charset=utf-8")
        # PAD に書き写すための記録（秘密情報は解決前＝プレースホルダのまま残す）
        shown = trace_body if trace_body is not None else body
        if shown is not None:
            shown = json.loads(mask_secrets(json.dumps(shown, ensure_ascii=False)))
        self.trace.append({"method": method, "path": path, "body": shown, "note": note})
        try:
            # localhost へはプロキシを経由させない（PAD でも同じ配慮が要る）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=60) as res:
                payload = json.loads(res.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                v = json.loads(detail).get("value", {})
                msg = f'{v.get("error", "")}: {v.get("message", "")[:200]}'
            except Exception:
                msg = detail[:200]
            raise RuntimeError(f"WebDriver エラー [{method} {path}] {msg}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"WebDriver に接続できません（{self.base}）: {e.reason}. "
                "msedgedriver.exe が起動しているか、プロキシ除外設定を確認してください。"
            ) from None
        return payload.get("value")

    # ---- セッション -------------------------------------------------------
    def start(self) -> str:
        body = {"capabilities": {"alwaysMatch": {"browserName": self.browser_name}}}
        value = self._call("POST", "/session", body, note="セッション開始（ブラウザ起動）")
        self.session_id = (value or {}).get("sessionId")
        if not self.session_id:
            raise RuntimeError("セッション ID を取得できませんでした")
        return self.session_id

    def _s(self, tail: str) -> str:
        return f"/session/{self.session_id}{tail}"

    def quit(self) -> None:
        if self.session_id:
            try:
                self._call("DELETE", self._s(""), note="セッション終了（ブラウザを閉じる）")
            except Exception:
                pass
            self.session_id = None

    # ---- 操作 -------------------------------------------------------------
    def navigate(self, url: str) -> None:
        self._call("POST", self._s("/url"), {"url": url}, note=f"ページを開く: {url}")

    def set_window(self, width: int, height: int) -> None:
        self._call("POST", self._s("/window/rect"),
                   {"width": int(width), "height": int(height)},
                   note=f"ウィンドウサイズ {width}x{height}")

    def execute(self, script: str, args: list, note: str = "",
                trace_args: list | None = None):
        trace_body = None
        if trace_args is not None:
            trace_body = {"script": script, "args": trace_args}
        return self._call("POST", self._s("/execute/sync"),
                          {"script": script, "args": args},
                          note=note, trace_body=trace_body)

    def screenshot(self, path: str) -> str:
        """スクリーンショットを保存する。ファイル名末尾に _YYYYMMDD_HHMMSS を付ける。
        （PAD では base64 を扱う代わりに、PAD 標準の「スクリーンショットを取得」でもよい）"""
        b64 = self._call("GET", self._s("/screenshot"), note="スクリーンショット取得（base64）")
        root, ext = os.path.splitext(path)
        ext = ext or ".png"
        out = f"{root}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64))
        return os.path.abspath(out)

    # ---- 高レベル（JS 一本化） -------------------------------------------
    def act(self, candidates: list, action: str, value: str = "", note: str = "") -> dict:
        resolved = resolve_secrets(value) if action == "fill" else value
        res = self.execute(JS_ACT, [list(candidates), action, resolved],
                           note=note,
                           trace_args=[list(candidates), action, value]) or {}
        if not res.get("ok"):
            raise RuntimeError(
                f"要素が見つからないか操作できません（action={action}, 候補={candidates}）")
        return res


# ---------------------------------------------------------------- ステップ実行
def _candidates(step: dict) -> list:
    """録画 JSON の selectors（[[sel], [sel], ...]）を平坦な候補リストにする。"""
    out = []
    for group in step.get("selectors", []):
        if isinstance(group, list):
            out.extend([s for s in group if isinstance(s, str)])
        elif isinstance(group, str):
            out.append(group)
    return out


def exec_step(drv: WebDriverHTTP, step: dict, values: dict, out_dir: str,
              log=print, tag: str = "") -> None:
    t = step.get("type")
    if t == "comment":
        log(f"  {tag}💬 {fill_value(step.get('text', ''), values)}")
        return
    if t == "setViewport":
        w, h = step.get("width"), step.get("height")
        if w and h:
            drv.set_window(w, h)
            log(f"  {tag}ウィンドウサイズ → {w}x{h}")
        return
    if t == "navigate":
        url = fill_value(step.get("url", ""), values)
        drv.navigate(url)
        log(f"  {tag}navigate {url}")
        return
    if t in ("click", "doubleClick"):
        cands = [fill_value(s, values) for s in _candidates(step)]
        res = drv.act(cands, "click", note=f"クリック {cands[:1]}")
        log(f"  {tag}クリック: {res.get('used')}")
        return
    if t == "change":
        cands = [fill_value(s, values) for s in _candidates(step)]
        val = fill_value(step.get("value", ""), values)
        res = drv.act(cands, "fill", val, note=f"入力 {cands[:1]}")
        log(f"  {tag}入力: {res.get('used')} ← 「{mask_secrets(val)}」")
        return
    if t == "screenshot":
        name = fill_value(step.get("name", "screenshot"), values)
        saved = drv.screenshot(os.path.join(out_dir, name + ".png"))
        log(f"  {tag}📸 {saved}")
        return
    if t == "assertText":                      # 完了メッセージの確認（任意）
        text = fill_value(step.get("text", ""), values)
        res = drv.act([], "exists", text, note=f"完了確認: {text}")
        log(f"  {tag}✔ 画面に「{text}」を確認")
        return
    log(f"  {tag}{t} … 未対応のためスキップ")


# ---------------------------------------------------------------- バッチ本体
def run(batch: dict, rows: list, common: dict, drv: WebDriverHTTP, out_dir: str,
        id_col: str, log=print, stop_on_error: bool = False) -> list:
    setup = batch.get("setup", [])
    loop = batch.get("loop", [])
    recover = batch.get("recover", [])
    teardown = batch.get("teardown", [])
    results = []

    log(f"── セットアップ（{len(setup)} ステップ）──")
    for i, st in enumerate(setup, 1):
        exec_step(drv, st, common, out_dir, log=log, tag=f"[setup {i}/{len(setup)}] ")

    total = len(rows)
    for n, row in enumerate(rows, 1):
        rid = str(row.get(id_col, "")).strip()
        if str(row.get("skip", "")).strip():
            log(f"[{n}/{total}] {rid} … スキップ（skip 列指定）")
            results.append({"ID": rid, "結果": "スキップ", "理由": "", "エビデンス": ""})
            continue
        values = dict(common)
        values.update(row)
        log(f"── [{n}/{total}] {rid} 開始 ──")
        shot = ""
        try:
            for i, st in enumerate(loop, 1):
                exec_step(drv, st, values, out_dir, log=log,
                          tag=f"[{n}/{total} step {i}/{len(loop)}] ")
                if st.get("type") == "screenshot":
                    shot = fill_value(st.get("name", ""), values)
            results.append({"ID": rid, "結果": "成功", "理由": "", "エビデンス": shot})
            log(f"── [{n}/{total}] {rid} ✅ 成功 ──")
        except Exception as e:
            reason = str(e)[:300]
            log(f"── [{n}/{total}] {rid} ❌ 失敗: {reason} ──")
            try:
                drv.screenshot(os.path.join(out_dir, f"fail_{rid}.png"))
            except Exception:
                pass
            results.append({"ID": rid, "結果": "失敗", "理由": reason, "エビデンス": ""})
            if stop_on_error:
                break
            for i, st in enumerate(recover, 1):
                try:
                    exec_step(drv, st, values, out_dir, log=log,
                              tag=f"[recover {i}/{len(recover)}] ")
                except Exception:
                    pass

    for i, st in enumerate(teardown, 1):
        try:
            exec_step(drv, st, common, out_dir, log=log,
                      tag=f"[teardown {i}/{len(teardown)}] ")
        except Exception:
            pass
    return results


# ---------------------------------------------------------------- trace 出力
def write_trace(trace: list, path: str, batch_title: str) -> str:
    """PAD に書き写すための「HTTP 呼び出しの実物」を Markdown で出力する。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        f"# PAD 手順書（自動生成）: {batch_title}",
        "",
        "各行が PAD の「Web サービスの呼び出し」1 アクションに対応する。",
        "URL の `{session}` は、最初の POST /session の応答から取り出した `value.sessionId` を入れる。",
        "秘密情報は `{{SECRET:...}}` のまま記載しているので、PAD 側で資格情報の変数に置き換えること。",
        "",
        "| # | メソッド | URL | 本文（JSON） | 意味 |",
        "|---|---|---|---|---|",
    ]
    import re
    for i, c in enumerate(trace, 1):
        # 実セッション ID を {session} に伏せる（毎回変わる値なので手順書には残さない）
        path_disp = re.sub(r"^/session/[^/]+", "/session/{session}", c["path"])
        body = c["body"]
        if body is None:
            body_disp = "（なし）"
        elif isinstance(body, dict) and "script" in body:
            # JS 本文は全ステップ共通なので、変わる部分（args）だけを載せる
            s = json.dumps(body.get("args", []), ensure_ascii=False)
            body_disp = "`script`=共通JS, `args`=" + "`" + s.replace("|", "\\|") + "`"
        else:
            s = json.dumps(body, ensure_ascii=False)
            body_disp = "`" + s.replace("|", "\\|") + "`"
        lines.append(f"| {i} | {c['method']} | `{path_disp}` | {body_disp} | {c['note']} |")
    lines += [
        "",
        "## 共通で使う JavaScript（`/execute/sync` の `script` に入れる）",
        "",
        "```javascript",
        JS_ACT.strip(),
        "```",
        "",
        "PAD では上記を 1 つのテキスト変数に入れておき、`args` だけを差し替える。",
        "`args` は `[[セレクタ候補の配列], \"click\" か \"fill\", 入力値]` の形。",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.abspath(path)


def _robin_js_chunks(js: str, width: int = 100) -> list:
    """長い 1 行は PAD への貼り付けで無視されるため、JS を短い行に分割して連結する。

      SET JsAct TO $'''<1つ目>'''
      SET JsAct TO $'''%JsAct%<2つ目>'''   ← %JsAct% で前の内容に継ぎ足す

    分割位置が単引用符に隣接すると `''''` のような紛らわしい並びになるため、
    境界が `'` に当たらないよう 1 文字ずつずらす。"""
    chunks, i = [], 0
    while i < len(js):
        end = min(i + width, len(js))
        while end < len(js) and (js[end - 1] == "'" or js[end] == "'"):
            end += 1
        chunks.append(js[i:end])
        i = end
    lines = []
    for n, c in enumerate(chunks):
        head = "" if n == 0 else "%JsAct%"
        lines.append(f"SET JsAct TO $'''{head}{c}'''")
    return lines


def _robin_safe_selector(sel: str) -> str:
    """Robin の $'''…''' リテラルには**単引用符を入れられない**（PAD が黙って無視する）。
    そこで `xpath///*[@id="X"]` のような形は、引用符の要らない `id/X` に変換する。
    それでも引用符が残る候補は Robin 生成時に落とす（_robin_filter_candidates）。"""
    m = re.match(r'^xpath//\*\[@id=[\'"]([^\'"]+)[\'"]\]$', sel)
    if m:
        return "id/" + m.group(1)
    m = re.match(r'^xpath///\*\[@id=[\'"]([^\'"]+)[\'"]\]$', sel)
    if m:
        return "id/" + m.group(1)
    return sel


def _robin_filter_candidates(cands: list) -> list:
    """単引用符を含む候補を除く（Robin リテラルに入れられないため）。
    すべて落ちてしまう場合は、CSS の id セレクタなど代替を残せないか呼び出し側で確認する。"""
    out = [c for c in (_robin_safe_selector(x) for x in cands) if "'" not in c]
    return out


def _robin_col_var(col: str, cols: list) -> str:
    """列名 → Robin の変数名（ASCII）。%Row['列名']% はリテラル内に単引用符が入り
    PAD が貼り付けを無視するため、ループ先頭で変数に取り出して %Col1% の形で使う。

    Col 番号は「ID 列を必ず Col1」にそろえる（write_robin が cols を id_col で
    事前に埋める）。以降は録画での出現順。"""
    if col not in cols:
        cols.append(col)
    return f"%Col{cols.index(col) + 1}%"


def _to_robin_var(text: str, cols: list) -> str:
    """{{列名}} を Robin の変数参照 %Col1% 等に変換する（{{SECRET:…}} は対象外）。"""
    return re.sub(r"\{\{(?!SECRET:)(\w+)\}\}",
                  lambda m: _robin_col_var(m.group(1), cols), str(text))


def _robin_str(s: str) -> str:
    """Robin の文字列リテラル。実機で確認した規則:
      * バックスラッシュは `\\\\` に二重化する（`\\%` は「エスケープされた %」と解釈され、
        変数展開の `%` が対応しなくなって貼り付けが無視される）
      * 単引用符は `\\'` にエスケープする（生のままだと貼り付けが無視される）
    なお `%…%` は変数展開なので、そのまま埋め込みたい値に `%` を含めないこと。"""
    return "$'''" + s.replace("\\", "\\\\").replace("'", "\\'") + "'''"


def _robin_under_base(path_str: str, out_dir: str) -> str:
    """out_dir 配下のパスは %BaseDir% 相対のリテラルにする。

    配布時に直すのが BaseDir の 1 行だけで済むようにするため。
    out_dir の外にあるパスは絶対パスのまま出す。"""
    base = out_dir.rstrip("\\/")
    sep = "\\"
    if path_str.lower().startswith((base + sep).lower()):
        rest = path_str[len(base) + 1:]
        esc = rest.replace("\\", "\\\\").replace("'", "\\'")
        return "$'''%BaseDir%" + "\\\\" + esc + "'''"
    return _robin_str(path_str)


def _safe_comment(text: str, cols: list) -> str:
    """Robin のコメント行に出す文字列。

    {{列名}} は変数参照に変換されるが、{{SECRET:…}} は変換対象外なので
    そのまま書くと生成物に未解決のプレースホルダが残る。
    コメントに秘密情報の名前を出す必要はないため、角かっこ表記に置き換える。"""
    t = _to_robin_var(text, cols)
    t = re.sub(r"\{\{SECRET:([^}]*)\}\}", r"[SECRET:\1]", t)
    t = t.replace("{{", "[").replace("}}", "]")
    return t


# ---------------------------------------------------------------- Robin 部品
# 実機で確認した必須引数。EncodeRequestBody: False が無いと本文が URL エンコードされ、
# WebDriver が invalid argument: missing command parameters を返して何も動かない。
_WEB_FLAGS = "EncodeRequestBody: False FailOnErrorStatus: False"


def _web(url: str, method: str, body: str, resp: str, status: str,
         indent: str = "") -> str:
    """Web サービス呼び出し 1 行。body が None なら RequestBody を省く（GET/DELETE 用）。"""
    b = f"RequestBody: {body} " if body else ""
    return (f"{indent}Web.InvokeWebService.InvokeWebService Url: {url} "
            f"Method: Web.Method.{method} Accept: AppJson ContentType: AppJson "
            f"{b}{_WEB_FLAGS} Response=> {resp} StatusCode=> {status}")


def _robin_shot(indent: str, file_var: str) -> list:
    """エビデンス取得。WebDriver の /screenshot はページの表示領域だけを返すので、
    デスクトップや他ウィンドウが写り込まず、フォーカスにも依存しない。
    変数名を ActObj / ActResp と分けるのは、直前の ok 判定を壊さないため。"""
    return [
        _web("ShotUrl", "Get", None, "ShotResp", "ShotStatus", indent),
        f"{indent}Variables.ConvertJsonToCustomObject Json: ShotResp CustomObject=> ShotObj",
        f"{indent}SET ShotB64 TO ShotObj['value']",
        f"{indent}File.ConvertFromBase64 Base64Text: ShotB64 File: {file_var} "
        f"IfFileExists: File.IfExists.DoNothing",
    ]


def _robin_fail(indent: str) -> list:
    """RowError が立っていたら、エビデンスと結果を記録して次の件へ。
    PrevFailed は件の先頭で True に置いてあるので、ここで触る必要はない。"""
    ind2 = indent + "    "
    return [
        f"{indent}IF RowError <> $'''''' THEN",
        f"{ind2}SET NgCount TO NgCount + 1",
        *_robin_shot(ind2, "FailShot"),
        f"{ind2}File.WriteText File: ResultFile "
        f"TextToWrite: $'''%RowId%,%RowKey%,失敗,\"%RowError%\",\"%FailShot%\",%RecStamp%''' "
        f"AppendNewLine: True IfFileExists: File.IfFileExists.Append",
        f"{ind2}File.WriteText File: LogFile "
        f"TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 失敗 %RowError%''' "
        f"AppendNewLine: True IfFileExists: File.IfFileExists.Append",
        f"{ind2}NEXT LOOP",
        f"{indent}END",
    ]


def _robin_act(cands: list, action: str, value: str, indent: str, note: str,
               step_no: int, cols: list) -> list:
    """要素操作 1 ステップ分の Robin（本文組み立て → Web サービス呼び出し → 成否判定）。"""
    cands = [_to_robin_var(c, cols) for c in _robin_filter_candidates(cands)]
    value = _to_robin_var(value, cols)
    # 注記はリテラルに入るため、単引用符を含めない形に整える
    note = _to_robin_var(note, cols).replace("'", "").replace("[", "").replace("]", "")
    body_args = json.dumps([cands, action, value], ensure_ascii=False)
    # %JsAct% は Robin 側で展開させたいので、文字列のまま残す
    # exists は「文字列が見つからない」、click/fill は「要素が見つからない」
    why = "画面に文字列がありません" if action == "exists" else "で要素が見つかりません"
    reason = (f"ステップ{step_no}（{note}）{why}" if action == "exists"
              else f"ステップ{step_no}（{note}）{why}")
    return [
        f"{indent}# [{step_no}] {note}",
        f"{indent}SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''",
        _web("ExecUrl", "Post", "ActBody", "ActResp", "ActStatus", indent),
        f"{indent}Variables.ConvertJsonToCustomObject Json: ActResp CustomObject=> ActObj",
        f"{indent}IF ActObj['value']['ok'] <> True THEN",
        f"{indent}    SET RowError TO $'''{reason}'''",
        f"{indent}END",
    ]


def _robin_act_best_effort(cands: list, action: str, value: str, indent: str,
                           note: str, cols: list) -> list:
    """復帰処理や後片付け用。成否を判定せず、通るところまで進める。"""
    cands = [_to_robin_var(c, cols) for c in _robin_filter_candidates(cands)]
    value = _to_robin_var(value, cols)
    note = _to_robin_var(note, cols).replace("'", "").replace("[", "").replace("]", "")
    body_args = json.dumps([cands, action, value], ensure_ascii=False)
    return [
        f"{indent}# {note}",
        f"{indent}SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''",
        _web("ExecUrl", "Post", "ActBody", "ActResp", "ActStatus", indent),
        f"{indent}WAIT 1",
    ]


def _split_login(setup: list) -> tuple:
    """setup を「ログイン部分」と「それ以外」に分ける。

    {{SECRET:…}} を入力するステップが 1 つでもあれば、そこから
    「最後の SECRET ステップの直後の click」までをログイン部分とみなす。
    録画の形によっては境界がずれるので、生成物にその旨のコメントを入れる。
    戻り値: (login_indices:set, has_login:bool)"""
    idx = [i for i, st in enumerate(setup)
           if st.get("type") == "change" and str(st.get("value", "")).startswith("{{SECRET:")]
    if not idx:
        return set(), False
    lo, hi = min(idx), max(idx)
    end = hi
    for j in range(hi + 1, len(setup)):
        if setup[j].get("type") in ("click", "doubleClick"):
            end = j
            break
    return set(range(lo, end + 1)), True


def _prescan_cols(steps: list, cols: list) -> None:
    """{{列名}} の参照を先に全部拾って cols を確定させる。

    結果 CSV のヘッダーを書く時点で列名が分かっていないと、業務キーの列名が
    プレースホルダのまま出力されてしまうため、emit の前に 1 周する。
    登録順は emit 時と同じなので Col 番号はずれない。"""
    for st in steps:
        for sel in _candidates(st):
            _to_robin_var(sel, cols)
        for key in ("value", "text", "name", "url"):
            v = st.get(key)
            if v is not None:
                _to_robin_var(v, cols)


def _lint_robin(lines: list, log=print) -> list:
    """生成した Robin を貼り付ける前に、実機で判明している落とし穴を機械的に洗う。

    PAD は解釈できない行をエラーも出さずに無視するため、生成時に気づけないと
    「貼り付けたのに一部のアクションが無い」という形で後から発覚する。
    検出するもの:
      * 長すぎる 1 行（黙って無視される）
      * `SET x TO %y%` — 変数を変数に代入するとき % で囲んではいけない
      * Web サービス呼び出しに EncodeRequestBody: False が無い
      * $'''…''' の中のエスケープされていない単引用符
    """
    warns = []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        # 未解決のプレースホルダはコメント行に残っていても不可。
        # 列名やSECRETの変換漏れをここで捕まえる。閉じかっこ側は見ない
        # （WebDriver の JSON 本文が正当に }}} で終わるため）。
        if "{{" in s:
            warns.append(f"{i}行: 未解決のプレースホルダが残っています: {s[:80]}")
        if s.startswith("#"):
            continue
        if len(ln) > 700:
            warns.append(f"{i}行: 1行が長すぎます（{len(ln)}文字）。分割してください")
        m = re.match(r"^SET\s+\w+\s+TO\s+%(\w+)%\s*$", s)
        if m:
            warns.append(
                f"{i}行: SET の右辺で % を使っています。"
                f"変数の代入は `TO {m.group(1)}` と裸で書きます: {s}")
        if "InvokeWebService" in s and "EncodeRequestBody: False" not in s:
            warns.append(f"{i}行: EncodeRequestBody: False がありません（本文がURLエンコードされます）")
        for lit in re.findall(r"\$'''(.*?)'''", s):
            body = lit.replace("\\'", "")
            if "'" in body:
                warns.append(f"{i}行: リテラル内の単引用符が未エスケープです（\\' にする）: {s[:80]}")
    for w in warns:
        log(f"  ⚠ {w}")
    return warns


def write_robin(batch: dict, details_path: str, id_col: str, path: str,
                driver_exe: str = r"C:\temp\msedgedriver.exe",
                out_dir: str = r"C:\temp", proxy: str = "") -> str:
    """PAD に貼り付けられる Robin コードを生成する。

    PAD のフローデザイナーはアクションのコピー＆ペーストにテキスト（Robin）を使うため、
    生成したコードをキャンバスに貼り付ければフローが組み上がる。

    生成されるフローの構造（docs/PAD_WebDriver.md と対応）:
      setup   … ドライバ起動 → セッション → ログイン → 起点へ移動 → 失敗検知(Halt)
      loop    … skip 判定 / 再実行絞り込み / 件数上限 / 復帰 / 1 件分の操作 / エビデンス
      recover … 失敗した件のあと、次の件の前に起点へ戻す（batch の recover を使う）
    """
    js_one = js_act_oneline()
    # ID 列を必ず Col1 にそろえる（明細 CSV の先頭列 = ID という運用に合わせる）
    cols: list = [id_col]
    L: list = []
    A = L.append

    setup = batch.get("setup", [])
    loop_steps = batch.get("loop", [])
    recover = batch.get("recover", [])
    teardown = batch.get("teardown", [])
    login_idx, has_login = _split_login(setup)

    # 列名を先に確定させる（結果 CSV のヘッダーで業務キーの列名が必要）
    for _sec in (setup, loop_steps, recover, teardown):
        _prescan_cols(_sec, cols)

    # 起点へ戻る URL（recover が空のときのフォールバックに使う）
    start_url = ""
    for st in setup:
        if st.get("type") == "navigate":
            start_url = st.get("url", "")
            break

    A("# ============================================================")
    A(f"# 自動生成: {batch.get('title', '')}")
    A("# 貼り付け方: PAD のフローデザイナーでキャンバスをクリックし Ctrl+V")
    A("# 前提: msedgedriver.exe（Edge と同じバージョン）／localhost をプロキシ除外")
    A("# 解説: docs/PAD_WebDriver.md")
    A("# ============================================================")
    A("")
    A("# --- 接続先：環境を切り替えるときはここを直す ---")
    A("# 練習サイト  : file:///C:/temp/index.html")
    A("# 本番サイト  : https://… （実環境の URL）")
    A(f"SET TargetUrl TO {_robin_str(start_url)}")
    A("")
    A("# --- プロキシ：社外サイトへ出るときだけ指定する ---")
    A("# WebDriver が起動するブラウザーは素のプロファイルで、Windows のプロキシ設定を")
    A("# 引き継がない。社内プロキシ経由でしか外部に出られない環境では下を有効にする。")
    A("# localhost と file:// はプロキシを通らないので、練習サイトは影響を受けない。")
    if proxy:
        A("# UseProxy を False にすると直結（練習サイト用）に戻る。")
        A("SET UseProxy TO True")
        A(f"SET ProxyAddr TO {_robin_str(proxy)}")
    else:
        A("# 使う場合: UseProxy を True にし、ProxyAddr にプロキシの host:port を書く。")
        A("SET UseProxy TO False")
        A("SET ProxyAddr TO $'''proxy.example.com:8080'''")
    A("")
    A("# --- フォルダ・ファイル：配布時に触るのはこの BaseDir だけにする ---")
    A(f"SET BaseDir TO {_robin_str(out_dir)}")
    A("# ※ BaseDir の末尾に \\ を付けないこと（%BaseDir%\\file.png が二重になる）")
    A(f"SET DriverExe TO {_robin_under_base(driver_exe, out_dir)}")
    A("SET DriverUrl TO $'''http://127.0.0.1:9515'''")
    A(f"SET DetailsFile TO {_robin_under_base(details_path, out_dir)}")
    A("SET ResultFile TO $'''%BaseDir%\\\\pad_result.csv'''")
    A("SET LogFile TO $'''%BaseDir%\\\\pad_progress.log'''")
    A("SET ShotDir TO $'''%BaseDir%'''")
    A("")
    A("# --- 運用スイッチ ---")
    A("# まず 1 にして 1 件だけ流し、画面と結果を目で確認してから増やす")
    A("SET MaxItems TO 1")
    A("# 失敗分だけを再実行するとき True（読み込み元と出力先が自動で切り替わる）")
    A("SET RetryMode TO False")
    if has_login:
        A("# manual = 人が手でログイン（PAD はパスワードを一切扱わない）★推奨")
        A("# auto   = 録画されたログイン手順を実行する")
        A("SET LoginMode TO $'''manual'''")
    A("IF RetryMode THEN")
    A("    SET DetailsFile TO $'''%BaseDir%\\\\pad_result.csv'''")
    A("    SET ResultFile TO $'''%BaseDir%\\\\pad_result_retry.csv'''")
    A("END")
    A("")
    A("# --- 要素操作の共通 JavaScript ---")
    A("# PAD は長すぎる 1 行を貼り付けても黙って無視するため、短い行に分けて継ぎ足す。")
    A("# （%JsAct% は直前までの内容。順番どおりに貼ること）")
    for line in _robin_js_chunks(js_one):
        A(line)
    A("# ※ 継ぎ足しがうまくいかない場合は、同時生成した pad_flow.jsact.js の中身を")
    A("#   「変数の設定」アクション（変数名 JsAct）の値の欄に手で貼り付けてもよい。")
    A("")
    A("# --- 古いドライバーが残っていたら終了する ---")
    A("# 前回の実行が異常終了すると msedgedriver がポート 9515 を掴んだまま残り、")
    A("# 新しいドライバーが起動できない（古い方が応答してしまう）。")
    A("System.TerminateProcess.TerminateProcessByName ProcessName: $'''msedgedriver'''")
    A("WAIT 1")
    A("")
    A("# --- WebDriver を起動 ---")
    A("System.RunApplication.RunApplication ApplicationPath: DriverExe "
      "CommandLineArguments: $'''--port=9515''' WindowStyle: System.ProcessWindowStyle.Hidden "
      "ProcessId=> DriverPid")
    A("WAIT 3")
    A("")
    A("# --- セッション開始（ブラウザ起動）---")
    A("# プロキシの有無は冒頭の UseProxy で切り替える。")
    A("SET SessionBody TO $'''{\"capabilities\": {\"alwaysMatch\": "
      "{\"browserName\": \"MicrosoftEdge\"}}}'''")
    A("IF UseProxy THEN")
    A("    SET SessionBody TO $'''{\"capabilities\": {\"alwaysMatch\": "
      "{\"browserName\": \"MicrosoftEdge\", \"proxy\": {\"proxyType\": \"manual\", "
      "\"httpProxy\": \"%ProxyAddr%\", \"sslProxy\": \"%ProxyAddr%\"}}}}'''")
    A("END")
    A("SET AppJson TO $'''application/json'''")
    A("SET NewUrl TO $'''%DriverUrl%/session'''")
    A(_web("NewUrl", "Post", "SessionBody", "SessionResp", "SessionStatus"))
    A("# ↓ 「sessionId がありません」と出たらこの行を有効にして生の応答を確認する")
    A("# Display.ShowMessageDialog.ShowMessage Title: $\'\'\'WebDriver 応答\'\'\' "
      "Message: SessionResp Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> BtnDbg")
    A("Variables.ConvertJsonToCustomObject Json: SessionResp CustomObject=> SessionObj")
    A("# カスタムオブジェクトはブラケット記法で参照する。ドット記法は使えない。")
    A("SET SessionId TO SessionObj['value']['sessionId']")
    A("# 以降で使い回す URL を組み立てておく（1 行を短く保つため）")
    A("SET ExecUrl TO $'''%DriverUrl%/session/%SessionId%/execute/sync'''")
    A("SET GoUrl TO $'''%DriverUrl%/session/%SessionId%/url'''")
    A("SET RectUrl TO $'''%DriverUrl%/session/%SessionId%/window/rect'''")
    A("SET ShotUrl TO $'''%DriverUrl%/session/%SessionId%/screenshot'''")
    A("SET QuitUrl TO $'''%DriverUrl%/session/%SessionId%'''")
    A("")

    # ---- setup ----
    A("# ================= セットアップ（最初に 1 回）=================")
    A("SET RowError TO $''''''")
    A("SET Halt TO False")
    n = 0
    emitted_dialog = False
    in_auto = False           # IF LoginMode = auto THEN … の中にいるか
    for i, st in enumerate(setup):
        t = st.get("type")

        # ログイン部分は auto ブロックに入れる。その手前で手動ログインのダイアログを出す。
        if has_login and i in login_idx and not emitted_dialog:
            emitted_dialog = True
            in_auto = True
            A("")
            A("# ---------- 手動ログイン（既定）----------")
            A("# フローを止めて人がログインする。PAD はパスワードを一度も受け取らないので、")
            A("# 変数ペイン・実行ログ・エラーメッセージのどこにも残らない。")
            A("# ★ ログインだけでなく、繰り返しの起点画面まで人が進めてから[OK]を押す。")
            A("#   ログイン後の画面構成はサイト側の都合で変わることがあり、機械的に")
            A("#   辿らせるより確実で、修正も要らない。")
            A("# WebDriver は自分が起動したブラウザーしか操作できない。別に開いてある")
            A("# 普段のブラウザーでログインしても、フローはそのタブを見られない。")
            A("IF LoginMode = $'''manual''' THEN")
            A("    Display.ShowMessageDialog.ShowMessage Title: $'''手動ログイン''' "
              "Message: $'''いま開いたブラウザーでログインし、繰り返しの起点画面まで"
              "進んでから[OK]を押してください。ブラウザーは閉じないでください。''' "
              "Icon: Display.Icon.Information Buttons: Display.Buttons.OKCancel "
              "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True "
              "ButtonPressed=> LoginBtn")
            A("    IF LoginBtn = $'''Cancel''' THEN")
            A("        SET Halt TO True")
            A("    END")
            A("END")
            A("")
            A("# ---------- 自動ログイン（LoginMode = auto のときだけ）----------")
            A("# ★ 資格情報はフローに直書きしない。下の 2 行は、デザイナーから")
            A("#   ［入力ダイアログを表示］を 2 つ置き（パスワード側は入力の種類を")
            A("#   「パスワード」にする）、生成変数を EdiUser / EdiPassword に")
            A("#   リネームしたものに置き換えること。")
            A("# ★ ログイン部分の範囲は SECRET プレースホルダの位置から機械的に判定している。")
            A("#   録画の形によっては境界がずれるので、貼り付け後に目で確認すること。")
            A("IF LoginMode = $'''auto''' THEN")
            A("    SET EdiUser TO $''''''")
            A("    SET EdiPassword TO $''''''")
            A("    # JSON 本文を壊さないよう \\ → \\\\ 、\" → \\\" の順でエスケープする。")
            A("    # 順序を守ること（逆にすると 1 段目で入れた \\\\ を 2 段目が書き換える）。")
            A("    # ActivateEscapeSequences: False が重要（True だと \\\\ が 1 個に戻る）。")
            # 生成物の他の箇所と同じく、二重引用符は素のまま書く（Robin では
            # " も \" も同じ意味だが、パス以外に単独のバックスラッシュを残さない）。
            BS, DQ = chr(92), chr(34)
            # 一時変数へ往復させる。1段目は var → varEsc、2段目は varEsc → var。
            # どちらの行も入力と出力が別変数なので、同一変数への書き戻し
            # （自己代入）が PAD で許されるかどうかに依存しない。
            # 最終的にエスケープ済みの値が元の変数に入るため、本文では
            # そのまま %EdiUser% / %EdiPassword% を参照できる。
            for var in ("EdiUser", "EdiPassword"):
                tmp = var + "Esc"
                A(f"    Text.Replace.ReplaceText Text: {var} "
                  f"TextToFind: $'''{BS}{BS}''' IgnoreCase: False "
                  f"ReplaceWith: $'''{BS}{BS}{BS}{BS}''' "
                  f"ActivateEscapeSequences: False "
                  f"ComparisonType: Text.TextComparisonType.CultureSensitive "
                  f"Result=> {tmp}")
                A(f"    Text.Replace.ReplaceText Text: {tmp} "
                  f"TextToFind: $'''{DQ}''' IgnoreCase: False "
                  f"ReplaceWith: $'''{BS}{BS}{DQ}''' "
                  f"ActivateEscapeSequences: False "
                  f"ComparisonType: Text.TextComparisonType.CultureSensitive "
                  f"Result=> {var}")

        # ★ 手動ログイン時は、ログイン以降のセットアップ手順（起点画面への移動）も
        #   人が進める前提にする。実サイトはログイン後の画面構成が録画時と変わる
        #   ことがあり、機械的に辿らせると起点に着けず Halt するため。
        #   よって auto ブロックはここでは閉じず、setup の最後まで続ける。

        ind = "    " if in_auto else ""

        if t == "comment":
            A(f"{ind}# 💬 {_safe_comment(st.get('text', ''), cols)}")
            continue
        if t == "setViewport":
            n += 1
            w = int(st.get("width", 1920) or 1920)
            h = int(st.get("height", 1080) or 1080)
            A(f"{ind}# [{n}] ウィンドウサイズ {w}x{h}")
            A(f"{ind}# エビデンスに写る範囲はこのサイズで決まる。複数の PC に配布する場合は")
            A(f"{ind}# 一番小さい画面に収まる値にそろえること。")
            A(f"{ind}SET RectBody TO $'''{{\"width\": {w}, \"height\": {h}}}'''")
            A(_web("RectUrl", "Post", "RectBody", "RectResp", "RectStatus", ind))
            continue
        if t == "navigate":
            n += 1
            A(f"{ind}# [{n}] ページを開く（URL は冒頭の TargetUrl で設定）")
            A(f"{ind}SET UrlBody TO $'''{{\"url\": \"%TargetUrl%\"}}'''")
            A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus", ind))
            A(f"{ind}WAIT 2")
            continue
        if t in ("click", "doubleClick", "change"):
            n += 1
            cands = _candidates(st)
            action = "fill" if t == "change" else "click"
            value = st.get("value", "")
            if str(value).startswith("{{SECRET:"):
                name = value[len("{{SECRET:"):-2]
                # エスケープ済み（上の Text.Replace で同変数に上書きしてある）
                value = "%EdiUser%" if "USER" in name.upper() else "%EdiPassword%"
            L.extend(_robin_act(cands, action, value, ind,
                                f"{action} {cands[0] if cands else ''}", n, cols))
            A(f"{ind}WAIT 1")
            continue

    if in_auto:
        # ログイン手順で setup が終わっている場合（後続のステップが無い場合）
        A("END")
        A("")
        A("# ---------- 使い終わったパスワードは即座に消す ----------")
        A("SET EdiPassword TO $''''''")
        A("SET EdiPasswordEsc TO $''''''")
    A("")
    A("# ---------- セットアップ失敗を検知して止める ----------")
    A("# ここで止めないと、ループ先頭で RowError がリセットされるため、")
    A("# 全件が「ステップ1で要素が見つかりません」という偽の失敗として記録される。")
    A("IF RowError <> $'''''' THEN")
    A("    SET Halt TO True")
    A("END")
    A("")

    # ---- 明細読み込み ----
    # SET の右辺で変数を参照するときは % で囲まない（%Col2% と書くと貼り付けが弾かれる）
    key_ref = "Col2" if len(cols) > 1 else "$''''''"
    A("# ================= 明細（CSV）を読み込む =================")
    A("IF Halt = False THEN")
    A("    File.ReadFromCSVFile.ReadCSV CSVFile: DetailsFile "
      "Encoding: File.CSVEncoding.UTF8 TrimFields: True "
      "FirstLineContainsColumnNames: True "
      "ColumnsSeparator: File.CSVColumnsSeparator.Comma CSVTable=> Rows")
    A("    # 結果 CSV は、そのまま明細として読み直せる列構成にする。")
    A("    # ID だけでなく業務キーも入れないと、再実行で対象を特定できない。")
    key_head = cols[1] if len(cols) > 1 else "業務キー"
    A(f"    File.WriteText File: ResultFile "
      f"TextToWrite: $'''{id_col},{key_head},結果,理由,エビデンス,実行日時''' "
      f"AppendNewLine: True IfFileExists: File.IfFileExists.Overwrite")
    A("    File.WriteText File: LogFile "
      "TextToWrite: $'''===== 実行開始 上限%MaxItems%件 RetryMode=%RetryMode% =====''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A("    SET OkCount TO 0")
    A("    SET NgCount TO 0")
    A("    SET SkipCount TO 0")
    A("    SET Attempted TO 0")
    A("    SET PrevFailed TO False")
    A("")

    # ---- ループ ----
    ind = "    "
    inner = "        "
    A(f"{ind}# ================= 明細ごとの繰り返し =================")
    A(f"{ind}LOOP FOREACH Row IN Rows")
    A(f"{inner}# 明細の列を変数に取り出す（リテラル内に単引用符を入れないため）")
    A("@@COLVARS@@")
    A(f"{inner}SET RowId TO Col1")
    A(f"{inner}SET RowKey TO {key_ref}")
    A(f"{inner}SET RowError TO $''''''")
    A("")
    A(f"{inner}# 再実行モードでは「失敗」行だけを対象にする")
    A(f"{inner}IF RetryMode THEN")
    A(f"{inner}    IF Row['結果'] <> $'''失敗''' THEN")
    A(f"{inner}        NEXT LOOP")
    A(f"{inner}    END")
    A(f"{inner}END")
    A("")
    A(f"{inner}# skip 列に値がある行は飛ばす（再実行 CSV には skip 列が無いので除外）")
    A(f"{inner}IF RetryMode = False THEN")
    A(f"{inner}    IF Row['skip'] <> $'''''' THEN")
    A(f"{inner}        SET SkipCount TO SkipCount + 1")
    A(f"{inner}        File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,スキップ,,,''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A(f"{inner}        NEXT LOOP")
    A(f"{inner}    END")
    A(f"{inner}END")
    A("")
    A(f"{inner}# 件数上限。打ち切った行も記録に残す（どこから再開するか分かる）")
    A(f"{inner}IF Attempted >= MaxItems THEN")
    A(f"{inner}    File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,未実行,\"件数上限 %MaxItems% 件に達したため\",,''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A(f"{inner}    NEXT LOOP")
    A(f"{inner}END")
    A(f"{inner}SET Attempted TO Attempted + 1")
    A("")
    A(f"{inner}# 直前の件が失敗していたら、起点に復帰してから始める。")
    A(f"{inner}# 失敗した画面のまま次の件を始めると 1 件の失敗が全件に連鎖する。")
    A(f"{inner}IF PrevFailed THEN")
    if recover:
        for st in recover:
            t = st.get("type")
            if t == "comment":
                A(f"{inner}    # 💬 {_safe_comment(st.get('text', ''), cols)}")
            elif t in ("click", "doubleClick", "change"):
                cands = _candidates(st)
                act = "fill" if t == "change" else "click"
                L.extend(_robin_act_best_effort(
                    cands, act, st.get("value", ""), inner + "    ",
                    f"復帰: {act} {cands[0] if cands else ''}", cols))
            elif t == "navigate":
                A(f"{inner}    SET UrlBody TO $'''{{\"url\": \"%TargetUrl%\"}}'''")
                A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus", inner + "    "))
                A(f"{inner}    WAIT 2")
    elif start_url:
        A(f"{inner}    # batch に recover が無いので、開始 URL を開き直して復帰する。")
        A(f"{inner}    # ログインが必要なサイトではセッションが切れる可能性があるため、")
        A(f"{inner}    # 録画に recover セクションを用意するほうが確実。")
        A(f"{inner}    SET UrlBody TO $'''{{\"url\": \"%TargetUrl%\"}}'''")
        A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus", inner + "    "))
        A(f"{inner}    WAIT 2")
    else:
        A(f"{inner}    # ★ 復帰手順が定義されていない。batch に recover を追加すること。")
        A(f"{inner}    #   このままでは 1 件失敗すると以降が連鎖して失敗する。")
    A(f"{inner}    SET PrevFailed TO False")
    A(f"{inner}END")
    A(f"{inner}# 悲観的に置く。最後まで通れば False に戻る（フラグを立てる箇所が 1 行で済む）")
    A(f"{inner}SET PrevFailed TO True")
    A("")
    A(f"{inner}# 日時つきのファイル名を作る。MM は月、mm は分。")
    A(f"{inner}DateTime.GetCurrentDateTime.Local "
      "DateTimeFormat: DateTime.DateTimeFormat.DateAndTime CurrentDateTime=> NowDt")
    A(f"{inner}Text.ConvertDateTimeToText.FromCustomDateTime DateTime: NowDt "
      "CustomFormat: $'''yyyyMMdd_HHmmss''' Result=> Stamp")
    A(f"{inner}Text.ConvertDateTimeToText.FromCustomDateTime DateTime: NowDt "
      "CustomFormat: $'''yyyy/MM/dd HH:mm:ss''' Result=> RecStamp")
    A(f"{inner}SET ShotPath TO $'''%ShotDir%\\\\%RowId%__%RowKey%__%Stamp%.png'''")
    A(f"{inner}SET FailShot TO $'''%ShotDir%\\\\fail__%RowId%__%RowKey%__%Stamp%.png'''")
    A(f"{inner}File.WriteText File: LogFile "
      "TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 開始''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A("")

    m = 0
    for st in loop_steps:
        t = st.get("type")
        if t == "comment":
            A(f"{inner}# 💬 {_safe_comment(st.get('text', ''), cols)}")
            continue
        if t == "screenshot":
            A(f"{inner}# エビデンス保存（%RowId%__%RowKey%__日時）")
            A(f"{inner}# WebDriver に撮らせるとページの表示領域だけが写る。")
            A(f"{inner}# デスクトップや他ウィンドウは写らず、フォーカスにも依存しない。")
            A(f"{inner}# 逆にスクロールしないと見えない範囲は写らない点に注意。")
            L.extend(_robin_shot(inner, "ShotPath"))
            A("")
            continue
        if t == "assertText":
            m += 1
            text = st.get("text", "")
            A(f"{inner}# 完了確認。「ボタンは押せたが実際には処理されていない」を検知する。")
            L.extend(_robin_act([], "exists", text, inner,
                                f"完了確認: {text}", m, cols))
            L.extend(_robin_fail(inner))
            A("")
            continue
        if t in ("click", "doubleClick", "change"):
            m += 1
            cands = _candidates(st)
            action = "fill" if t == "change" else "click"
            L.extend(_robin_act(cands, action, st.get("value", ""), inner,
                                f"{action} {cands[0] if cands else ''}", m, cols))
            L.extend(_robin_fail(inner))
            A(f"{inner}WAIT 1")
            A("")
            continue

    A(f"{inner}# ここまで来たら成功")
    A(f"{inner}SET PrevFailed TO False")
    A(f"{inner}SET OkCount TO OkCount + 1")
    A(f"{inner}File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,成功,,\"%ShotPath%\",%RecStamp%''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A(f"{inner}File.WriteText File: LogFile "
      "TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 成功''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A(f"{ind}END")
    A("END")
    A("")

    # ---- teardown / 後片付け ----
    if teardown:
        A("# ================= 後処理（batch の teardown）=================")
        for st in teardown:
            t = st.get("type")
            if t == "comment":
                A(f"# 💬 {_safe_comment(st.get('text', ''), cols)}")
            elif t in ("click", "doubleClick", "change"):
                cands = _candidates(st)
                act = "fill" if t == "change" else "click"
                L.extend(_robin_act_best_effort(
                    cands, act, st.get("value", ""), "",
                    f"後処理: {act} {cands[0] if cands else ''}", cols))
        A("")

    A("# ================= 後片付け =================")
    A(_web("QuitUrl", "Delete", None, "QuitResp", "QuitStatus"))
    A("System.TerminateProcess.TerminateProcessByName ProcessName: $'''msedgedriver'''")
    A("IF Halt = False THEN")
    A("    Display.ShowMessageDialog.ShowMessage Title: $'''完了''' "
      "Message: $'''成功 %OkCount% / 失敗 %NgCount% / スキップ %SkipCount%"
      "（上限 %MaxItems% 件）  結果CSV: %ResultFile%''' "
      "Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> Btn")
    A("END")
    A("IF Halt THEN")
    A("    Display.ShowMessageDialog.ShowMessage Title: $'''中止''' "
      "Message: $'''ログインまたは起点への移動に失敗したため、明細を1件も処理せず"
      "中止しました。pad_progress.log を確認してください。''' "
      "Icon: Display.Icon.Warning Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> Btn")
    A("END")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # 収集した参照列を、ループ先頭の変数取り出しに展開する（Col1 = ID 列）
    colvars = "\n".join(
        f"        SET Col{i + 1} TO Row['{c}']" for i, c in enumerate(cols)
    )
    body = "\n".join(L).replace("@@COLVARS@@", colvars)
    warns = _lint_robin(body.split("\n"))
    if warns:
        print(f"  ⚠ 上記 {len(warns)} 件は貼り付けが無視される可能性があります")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    # 共通 JavaScript は別ファイルにも出す（長い 1 行が貼れないときの逃げ道）
    js_path = os.path.splitext(path)[0]
    if js_path.endswith(".robin"):
        js_path = js_path[: -len(".robin")]
    js_path += ".jsact.js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_one + "\n")
    return os.path.abspath(path)


def main() -> None:
    p = argparse.ArgumentParser(
        description="PAD 版バッチの参照実装（WebDriver を HTTP 直叩き・拡張機能不要）")
    p.add_argument("--batch", required=True, help="バッチ定義 JSON")
    p.add_argument("--details", required=True, help="明細 CSV / xlsx")
    p.add_argument("--values", help="共通値 JSON（任意）")
    p.add_argument("--id-column", help="ID 列（既定: 先頭列）")
    p.add_argument("--driver-url", default="http://127.0.0.1:9515",
                   help="WebDriver の URL（既定: http://127.0.0.1:9515）")
    p.add_argument("--browser-name", default="MicrosoftEdge",
                   help="MicrosoftEdge / chrome")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--trace", help="PAD 用手順書（Markdown）の出力先")
    p.add_argument("--robin", help="PAD に貼り付ける Robin コードの出力先（ブラウザ操作は不要）")
    p.add_argument("--driver-exe", default=r"C:\WebDriver\msedgedriver.exe",
                   help="Robin 生成時に埋め込む msedgedriver のパス")
    p.add_argument("--pad-out-dir", default=r"C:\PAD\output",
                   help="Robin 生成時に埋め込む出力フォルダ")
    p.add_argument("--proxy", default="",
                   help="外部サイト用プロキシ host:port（例 proxy.example.com:8080）。"
                        "localhost/file:// は通さない。省略時はプロキシなし")
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--stop-on-error", action="store_true")
    args = p.parse_args()

    batch = load_recording(args.batch)
    common = load_recording(args.values) if args.values else {}
    # Robin 生成のみの場合、--details は「会社 PC 側のパス」でよく、手元に実体が無くてよい
    if args.robin and not os.path.exists(args.details):
        headers, rows = [args.id_column or "ID"], []
    else:
        headers, rows = load_details(args.details)
        if not rows and not args.robin:
            sys.exit("明細が 0 件です: " + args.details)
    id_col = args.id_column or headers[0]
    if id_col not in headers:
        sys.exit(f"ID 列 '{id_col}' が明細の列名にありません: {headers}")
    if args.max_items:
        rows = rows[:args.max_items]

    if args.robin:
        out = write_robin(batch, args.details, id_col, args.robin,
                          args.driver_exe, args.pad_out_dir, args.proxy)
        js_out = out[:-len(".robin.txt")] + ".jsact.js" if out.endswith(".robin.txt") \
            else os.path.splitext(out)[0] + ".jsact.js"
        print(f"📄 PAD 用 Robin コード: {out}")
        print(f"📄 共通 JavaScript   : {js_out}")
        print(f"   → .js は PAD 実行 PC の {args.pad_out_dir} に置くこと")
        if not args.trace:
            return

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logf = open(os.path.join(args.out_dir, f"pad_{stamp}.log"), "w", encoding="utf-8")

    def log(msg: str = "") -> None:
        print(msg)
        logf.write(str(msg) + "\n")
        logf.flush()

    log(f"バッチ: {batch.get('title', '')}")
    log(f"明細: {args.details}（{len(rows)} 件 / ID列: {id_col}）")
    log(f"WebDriver: {args.driver_url}")

    trace: list = []
    drv = WebDriverHTTP(args.driver_url, args.browser_name, trace)
    results = None
    try:
        drv.start()
        results = run(batch, rows, common, drv, args.out_dir, id_col,
                      log=log, stop_on_error=args.stop_on_error)
    except Exception as e:
        log(f"\n❌ 続行できないエラーで中断しました: {str(e)[:300]}")
        log("   よくある原因: (1) msedgedriver.exe が未起動 "
            "(2) Edge とドライバのバージョン不一致 "
            "(3) {{SECRET:...}} の環境変数が未設定 (4) 開始 URL に到達できない")
    finally:
        drv.quit()

    if args.trace:
        log(f"\n📄 PAD 用手順書: {write_trace(trace, args.trace, batch.get('title', ''))}")

    if results is None:
        logf.close()
        sys.exit(2)

    import csv as _csv
    rp = os.path.join(args.out_dir, f"pad_result_{stamp}.csv")
    with open(rp, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=["ID", "結果", "理由", "エビデンス"])
        w.writeheader()
        w.writerows(results)
    ok = sum(1 for r in results if r["結果"] == "成功")
    ng = sum(1 for r in results if r["結果"] == "失敗")
    sk = sum(1 for r in results if r["結果"] == "スキップ")
    log(f"\n===== 結果: {len(results)} 件中  成功 {ok} / 失敗 {ng} / スキップ {sk} =====")
    log(f"結果 CSV: {rp}")
    logf.close()
    if ng:
        sys.exit(1)


if __name__ == "__main__":
    main()
