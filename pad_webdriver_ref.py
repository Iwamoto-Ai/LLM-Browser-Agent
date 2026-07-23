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
    PAD が貼り付けを無視するため、ループ先頭で変数に取り出して %Col1% の形で使う。"""
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


def _robin_act(cands: list, action: str, value: str, indent: str, note: str,
               step_no: int, cols: list) -> list:
    """要素操作 1 ステップ分の Robin（本文組み立て → Web サービス呼び出し → 成否判定）。"""
    cands = [_to_robin_var(c, cols) for c in _robin_filter_candidates(cands)]
    value = _to_robin_var(value, cols)
    # 注記はリテラルに入るため、単引用符を含めない形に整える
    note = _to_robin_var(note, cols).replace("'", "").replace("[", "").replace("]", "")
    body_args = json.dumps([cands, action, value], ensure_ascii=False)
    # %JsAct% と %Row['列名']% は Robin 側で展開させたいので、文字列のまま残す
    return [
        f"{indent}# [{step_no}] {note}",
        f"{indent}SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''",
        f"{indent}Web.InvokeWebService.InvokeWebService Url: ExecUrl Method: Web.Method.Post "
        f"Accept: AppJson ContentType: AppJson RequestBody: ActBody "
        f"FailOnErrorStatus: False "
        f"Response=> ActResp StatusCode=> ActStatus",
        f"{indent}Variables.ConvertJsonToCustomObject Json: ActResp CustomObject=> ActObj",
        f"{indent}IF ActObj['value']['ok'] <> True THEN",
        f"{indent}    SET RowError TO $'''ステップ{step_no}（{note}）で要素が見つかりません'''",
        f"{indent}END",
    ]


def write_robin(batch: dict, details_path: str, id_col: str, path: str,
                driver_exe: str = r"C:\WebDriver\msedgedriver.exe",
                out_dir: str = r"C:\PAD\output") -> str:
    """PAD に貼り付けられる Robin コードを生成する。

    PAD のフローデザイナーはアクションのコピー＆ペーストにテキスト（Robin）を使うため、
    生成したコードをキャンバスに貼り付ければフローが組み上がる。
    ※ アクション名や引数は PAD のバージョンで差異があるため、`※要確認` を付けた行は
      実機で同じアクションを 1 つ置いてコピーし、差分があれば置き換えること。
    """
    js_one = js_act_oneline()
    cols: list = []          # 明細で参照する列名（%Col1%, %Col2%, … の順）
    L: list = []
    A = L.append

    A("# ============================================================")
    A(f"# 自動生成: {batch.get('title', '')}")
    A("# 貼り付け方: PAD のフローデザイナーでキャンバスをクリックし Ctrl+V")
    A("# 前提: msedgedriver.exe（Edge と同じバージョン）／localhost をプロキシ除外")
    A("# ※要確認 と書いた行は、PAD のバージョンでアクション名・引数が異なる場合がある")
    A("# ============================================================")
    A("")
    A("# --- 設定（環境に合わせて変更する） ---")
    A(f"SET DriverExe TO {_robin_str(driver_exe)}")
    A("SET DriverUrl TO $'''http://127.0.0.1:9515'''")
    A(f"SET DetailsFile TO {_robin_str(details_path)}")
    A(f"SET OutDir TO {_robin_str(out_dir)}")
    A("# ※ OutDir の末尾に \\ を付けないこと（%OutDir%\\file.png が二重になる）")
    A("# 資格情報はフローに直書きしない。PAD の資格情報か暗号化変数に入れて参照する。")
    A("SET EdiUser TO $'''%YourCredentialUser%'''")
    A("SET EdiPassword TO $'''%YourCredentialPassword%'''")
    A("")
    A("# --- 要素操作の共通 JavaScript ---")
    A("# PAD は長すぎる 1 行を貼り付けても黙って無視するため、短い行に分けて継ぎ足す。")
    A("# （%JsAct% は直前までの内容。順番どおりに貼ること）")
    for line in _robin_js_chunks(js_one):
        A(line)
    A("# ※ もし継ぎ足しがうまくいかない場合は、同時生成した pad_flow.jsact.js の中身を")
    A("#   「変数の設定」アクション（変数名 JsAct）の値の欄に手で貼り付けてもよい。")
    A("")
    A("# --- WebDriver を起動 ---  ※要確認（アクション名）")
    A("System.RunApplication.RunApplication ApplicationPath: DriverExe "
      "CommandLineArguments: $'''--port=9515''' WindowStyle: System.ProcessWindowStyle.Hidden "
      "ProcessId=> DriverPid")
    A("WAIT 3")
    A("")
    A("# --- セッション開始（ブラウザ起動）---")
    A("SET SessionBody TO $'''{\"capabilities\": {\"alwaysMatch\": "
      "{\"browserName\": \"MicrosoftEdge\"}}}'''")
    A("SET AppJson TO $'''application/json'''")
    A("SET NewUrl TO $'''%DriverUrl%/session'''")
    A("Web.InvokeWebService.InvokeWebService Url: NewUrl Method: Web.Method.Post "
      "Accept: AppJson ContentType: AppJson RequestBody: SessionBody "
      "FailOnErrorStatus: False "
      "Response=> SessionResp StatusCode=> SessionStatus")
    A("# ↓ ここで「sessionId がありません」と出たら、WebDriver がセッションを作れていない。")
    A("#   下の 1 行を有効にすると、WebDriver からの生の応答（原因）を確認できる。")
    A("# Display.ShowMessageDialog.ShowMessage Title: $\'\'\'WebDriver 応答\'\'\' "
      "Message: SessionResp Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> BtnDbg")
    A("Variables.ConvertJsonToCustomObject Json: SessionResp CustomObject=> SessionObj")
    A("SET SessionId TO SessionObj['value']['sessionId']")
    A("# 以降で使い回す URL を組み立てておく（1 行を短く保つため）")
    A("SET ExecUrl TO $'''%DriverUrl%/session/%SessionId%/execute/sync'''")
    A("SET GoUrl TO $'''%DriverUrl%/session/%SessionId%/url'''")
    A("SET RectUrl TO $'''%DriverUrl%/session/%SessionId%/window/rect'''")
    A("SET QuitUrl TO $'''%DriverUrl%/session/%SessionId%'''")
    A("")

    # ---- setup ----
    A("# ================= セットアップ（最初に 1 回）=================")
    A("SET RowError TO $\'\'\'\'\'\'")
    n = 0
    for st in batch.get("setup", []):
        t = st.get("type")
        n += 1
        if t == "comment":
            A(f"# 💬 {_to_robin_var(st.get('text', ''), cols)}")
            n -= 1
        elif t == "setViewport":
            A(f"# [{n}] ウィンドウサイズ {st.get('width')}x{st.get('height')}")
            A(f"SET RectBody TO $'''{{\"width\": {int(st.get('width', 1400))}, "
              f"\"height\": {int(st.get('height', 900))}}}'''")
            A("Web.InvokeWebService.InvokeWebService Url: RectUrl Method: Web.Method.Post "
              "Accept: AppJson ContentType: AppJson RequestBody: RectBody "
              "FailOnErrorStatus: False "
              "Response=> RectResp StatusCode=> RectStatus")
        elif t == "navigate":
            url = st.get("url", "")
            A(f"# [{n}] ページを開く")
            A(f"SET UrlBody TO $'''{{\"url\": \"{url}\"}}'''")
            A("Web.InvokeWebService.InvokeWebService Url: GoUrl Method: Web.Method.Post "
              "Accept: AppJson ContentType: AppJson RequestBody: UrlBody "
              "FailOnErrorStatus: False "
              "Response=> UrlResp StatusCode=> UrlStatus")
            A("WAIT 2")
        elif t in ("click", "doubleClick", "change"):
            cands = _candidates(st)
            action = "fill" if t == "change" else "click"
            value = st.get("value", "")
            # {{SECRET:XXX}} は PAD の変数参照に置き換える
            if value.startswith("{{SECRET:"):
                name = value[len("{{SECRET:"):-2]
                value = "%EdiUser%" if "USER" in name.upper() else "%EdiPassword%"
            L.extend(_robin_act(cands, action, value, "",
                                f"{action} {cands[0] if cands else ''}", n, cols))
            A("WAIT 1")
    A("")
    A("# ※ セットアップ（ログイン）に失敗した場合は、以降の全件が失敗として記録される。")
    A("#   pad_progress.log と結果 CSV を見て、ログイン部分から確認すること。")
    A("")

    # ---- 明細読み込み ----
    A("# ================= 明細（CSV）を読み込む =================")
    A("File.ReadFromCSVFile.ReadCSV CSVFile: DetailsFile Encoding: File.CSVEncoding.UTF8 "
      "TrimFields: True FirstLineContainsColumnNames: True "
      "ColumnsSeparator: File.CSVColumnsSeparator.Comma CSVTable=> Rows")
    A(f"SET ResultFile TO $'''%OutDir%\\\\pad_result.csv'''")
    A("File.WriteText File: ResultFile TextToWrite: $'''ID,結果,理由,エビデンス''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Overwrite")
    A("SET OkCount TO 0")
    A("SET NgCount TO 0")
    A("SET SkipCount TO 0")
    A("")

    # ---- ループ ----
    A("# ================= 明細ごとの繰り返し =================")
    A("LOOP FOREACH Row IN Rows")
    ind = "    "
    A(f"{ind}# 明細の列を変数に取り出す（リテラル内に単引用符を入れないため）")
    A("@@COLVARS@@")
    A(f"{ind}SET RowId TO Row['{id_col}']")
    A(f"{ind}SET RowError TO $''''''")
    A(f"{ind}IF Row['skip'] <> $'''''' THEN")
    A(f"{ind}    SET SkipCount TO SkipCount + 1")
    A(f"{ind}    File.WriteText File: ResultFile TextToWrite: $'''%RowId%,スキップ,,''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A(f"{ind}    NEXT LOOP")
    A(f"{ind}END")
    A(f"{ind}# 進捗表示（headless でも見えるようにログにも残す）")
    A(f"{ind}File.WriteText File: $'''%OutDir%\\\\pad_progress.log''' "
      "TextToWrite: $'''%RowId% 開始''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")

    m = 0
    for st in batch.get("loop", []):
        t = st.get("type")
        if t == "comment":
            A(f"{ind}# 💬 {_to_robin_var(st.get('text', ''), cols)}")
            continue
        if t == "screenshot":
            name = st.get("name", "shot")
            A(f"{ind}# エビデンス保存（プロジェクト番号__発注番号 で一意になる）")
            A(f"{ind}# 日時も入れたい場合は「現在の日時を取得」→「日時をテキストに変換」")
            A(f"{ind}# （書式 yyyyMMdd_HHmmss）を UI で追加し、ファイル名に足すこと。")
            A(f"{ind}# 既定の日時書式は / や : を含み、そのままではファイル名に使えない。")
            A(f"{ind}SET ShotName TO {_robin_str(_to_robin_var(name, cols))}")
            A(f"{ind}Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile "
              "File: $'''%OutDir%\\\\%ShotName%.png''' "
              "ImageFormat: System.ImageFormat.Png")
            continue
        if t == "assertText":
            text = st.get("text", "")
            L.extend(_robin_act([], "exists", text, ind, f"完了確認: {text}", m + 1, cols))
            continue
        if t in ("click", "doubleClick", "change"):
            m += 1
            cands = _candidates(st)
            action = "fill" if t == "change" else "click"
            value = st.get("value", "")
            L.extend(_robin_act(cands, action, value, ind,
                                f"{action} {cands[0] if cands else ''}", m, cols))
            A(f"{ind}IF RowError <> $'''''' THEN")
            A(f"{ind}    SET NgCount TO NgCount + 1")
            A(f"{ind}    File.WriteText File: ResultFile "
              "TextToWrite: $'''%RowId%,失敗,%RowError%,''' AppendNewLine: True "
              "IfFileExists: File.IfFileExists.Append")
            A(f"{ind}    NEXT LOOP")
            A(f"{ind}END")
            A(f"{ind}WAIT 1")

    A(f"{ind}SET OkCount TO OkCount + 1")
    A(f"{ind}File.WriteText File: ResultFile TextToWrite: $'''%RowId%,成功,,''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A("END")
    A("")
    A("# ================= 後片付け =================")
    A("Web.InvokeWebService.InvokeWebService Url: QuitUrl Method: Web.Method.Delete "
      "Accept: AppJson ContentType: AppJson FailOnErrorStatus: False "
      "Response=> QuitResp StatusCode=> QuitStatus")
    A("System.TerminateProcess.TerminateProcessByName ProcessName: $'''msedgedriver'''")
    A("Display.ShowMessageDialog.ShowMessage Title: $'''完了''' "
      "Message: $'''成功 %OkCount% / 失敗 %NgCount% / スキップ %SkipCount%''' "
      "Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> Btn")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # 収集した参照列を、ループ先頭の変数取り出しに展開する
    colvars = "\n".join(
        f"    SET Col{i + 1} TO Row['{c}']" for i, c in enumerate(cols)
    ) or "    # （明細の列を参照するステップはありません）"
    body = "\n".join(L).replace("@@COLVARS@@", colvars)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    # 共通 JavaScript は別ファイルに出す（Robin 側は File.ReadTextFromFile で読む）
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
                          args.driver_exe, args.pad_out_dir)
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
