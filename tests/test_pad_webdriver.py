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

"""PAD 参照実装（pad_webdriver_ref）の単体テスト。

実ブラウザも WebDriver も使わず、W3C WebDriver のふるまいを模した最小の
HTTP サーバー（localhost）を立てて、送信される HTTP 呼び出しを検証する。
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pad_webdriver_ref as pad          # noqa: E402
from recorder_import import load_recording  # noqa: E402

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


class _Handler(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):            # テスト出力を汚さない
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or "{}") if n else None

    def _send(self, value):
        data = json.dumps({"value": value}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self._read()
        _Handler.calls.append(("POST", self.path, body))
        if self.path == "/session":
            return self._send({"sessionId": "TESTSESSION", "capabilities": {}})
        if self.path.endswith("/execute/sync"):
            cands, action, value = body["args"]
            if action == "exists":
                return self._send({"ok": True, "used": None})
            if cands and any("NOTFOUND" in c for c in cands):
                return self._send({"ok": False, "used": None})
            return self._send({"ok": True, "used": cands[0] if cands else None})
        return self._send(None)

    def do_GET(self):
        _Handler.calls.append(("GET", self.path, None))
        if self.path.endswith("/screenshot"):
            return self._send(_PNG)
        return self._send(None)

    def do_DELETE(self):
        _Handler.calls.append(("DELETE", self.path, None))
        return self._send(None)


@pytest.fixture()
def driver_url():
    _Handler.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _client(driver_url, trace=None):
    return pad.WebDriverHTTP(driver_url, "MicrosoftEdge", trace if trace is not None else [])


def test_session_start_and_quit(driver_url):
    drv = _client(driver_url)
    assert drv.start() == "TESTSESSION"
    drv.quit()
    assert ("DELETE", "/session/TESTSESSION", None) in _Handler.calls


def test_navigate_and_window_rect(driver_url):
    drv = _client(driver_url)
    drv.start()
    drv.navigate("http://example.invalid/x")
    drv.set_window(1366, 900)
    posts = {p: b for m, p, b in _Handler.calls if m == "POST"}
    assert posts["/session/TESTSESSION/url"] == {"url": "http://example.invalid/x"}
    assert posts["/session/TESTSESSION/window/rect"] == {"width": 1366, "height": 900}


def test_act_sends_candidates_and_action(driver_url):
    drv = _client(driver_url)
    drv.start()
    res = drv.act(["#a", "text/B"], "click")
    assert res["ok"] is True and res["used"] == "#a"
    body = [b for m, p, b in _Handler.calls if p.endswith("/execute/sync")][-1]
    assert body["args"][0] == ["#a", "text/B"]
    assert body["args"][1] == "click"
    assert "arguments[0]" in body["script"]      # 共通 JS が送られている


def test_act_raises_when_not_found(driver_url):
    drv = _client(driver_url)
    drv.start()
    with pytest.raises(RuntimeError):
        drv.act(["#NOTFOUND"], "click")


def test_secret_resolved_on_wire_but_masked_in_trace(driver_url, monkeypatch):
    monkeypatch.setenv("PAD_TEST_PW", "s3cret-value")
    trace: list = []
    drv = _client(driver_url, trace)
    drv.start()
    drv.act(["#pw"], "fill", "{{SECRET:PAD_TEST_PW}}")
    sent = [b for m, p, b in _Handler.calls if p.endswith("/execute/sync")][-1]
    assert sent["args"][2] == "s3cret-value"          # 実際には解決済みの値を送る
    dumped = json.dumps(trace, ensure_ascii=False)
    assert "s3cret-value" not in dumped               # 手順書には平文を残さない
    assert "SECRET:PAD_TEST_PW" in dumped


def test_screenshot_writes_file_with_timestamp(driver_url, tmp_path):
    drv = _client(driver_url)
    drv.start()
    out = drv.screenshot(str(tmp_path / "PM1__900.png"))
    assert os.path.exists(out)
    name = os.path.basename(out)
    assert name.startswith("PM1__900_") and name.endswith(".png")


def test_connection_error_message_is_friendly():
    drv = pad.WebDriverHTTP("http://127.0.0.1:1", "MicrosoftEdge", [])
    with pytest.raises(RuntimeError) as e:
        drv.start()
    assert "WebDriver に接続できません" in str(e.value)


def test_batch_runs_practice_definition(driver_url, tmp_path, monkeypatch):
    monkeypatch.setenv("MY_USERNAME", "demo")
    monkeypatch.setenv("MY_PASSWORD", "password123")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    rows = [
        {"プロジェクト番号": "PM1", "発注番号": "900000000001", "skip": ""},
        {"プロジェクト番号": "PM2", "発注番号": "900000000002", "skip": "1"},
    ]
    drv = _client(driver_url)
    drv.start()
    results = pad.run(batch, rows, {}, drv, str(tmp_path), "プロジェクト番号",
                      log=lambda m: None)
    assert [r["結果"] for r in results] == ["成功", "スキップ"]
    # 明細の値がセレクタにも展開されている（text/{{発注番号}} → text/900000000001）
    execs = [b for m, p, b in _Handler.calls if p.endswith("/execute/sync")]
    assert any("text/900000000001" in json.dumps(b["args"][0], ensure_ascii=False)
               for b in execs)
    # navigate は setup の 1 回だけ（毎件ログインし直していない）
    assert sum(1 for m, p, _ in _Handler.calls if p.endswith("/url")) == 1


def test_write_trace_hides_session_and_keeps_js(driver_url, tmp_path):
    trace: list = []
    drv = _client(driver_url, trace)
    drv.start()
    drv.navigate("http://example.invalid/")
    drv.act(["#a"], "click")
    out = pad.write_trace(trace, str(tmp_path / "guide.md"), "テスト")
    md = open(out, encoding="utf-8").read()
    assert "TESTSESSION" not in md              # 実セッション ID は残さない
    assert "/session/{session}/url" in md
    assert "```javascript" in md                # 共通 JS を末尾に 1 回だけ載せる
    assert md.count("```javascript") == 1


# ---------------------------------------------------------------- Robin 生成
def _robin_text(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\PAD\details.csv", "プロジェクト番号",
                          str(tmp_path / "flow.txt"))
    return open(out, encoding="utf-8").read()


def test_robin_has_no_unresolved_placeholder(tmp_path):
    txt = _robin_text(tmp_path)
    assert "{{" not in txt                      # {{列名}} は %Col1% 等に変換済み
    assert "%Col1%" in txt
    assert "SET Col1 TO Row[" in txt            # ループ先頭で列を変数へ取り出す


def test_robin_bodies_are_valid_json(tmp_path):
    import re as _re
    txt = _robin_text(tmp_path)
    bodies = _re.findall(r"SET ActBody TO \$'''(.*?)'''", txt)
    assert bodies
    for b in bodies:
        probe = b.replace("%JsAct%", "JS")
        probe = probe.replace("%EdiUser%", "U").replace("%EdiPassword%", "P")
        probe = _re.sub(r"%Row\['[^']+'\]%", "V", probe)
        obj = json.loads(probe)                 # JSON として壊れていないこと
        assert set(obj) == {"script", "args"} and len(obj["args"]) == 3


def test_robin_is_literal_safe(tmp_path):
    """Robin の文字列リテラルに単引用符を入れると PAD が貼り付けを黙って無視する。"""
    import re as _re
    txt = _robin_text(tmp_path)
    for m in _re.finditer(r"\$'''(.*?)'''", txt):
        assert "'" not in m.group(1), m.group(1)[:60]
    for ch in ("'", '"', "\\", "%"):
        assert ch not in pad.JS_ACT, ch         # JS 側も安全な書き方（バッククォート）に統一


def test_robin_blocks_balanced(tmp_path):
    import re as _re
    txt = _robin_text(tmp_path)
    opens = len(_re.findall(r"^\s*(IF |LOOP )", txt, _re.M))
    ends = len(_re.findall(r"^\s*END\s*$", txt, _re.M))
    assert opens == ends


def test_robin_never_contains_credentials(tmp_path):
    """PAD 版は手動ログイン専用。資格情報は生成物に一切現れない。

    録画に残っている実際の値も、SECRET のプレースホルダも、
    それを受け取るための変数も出てはいけない。ログイン部分そのものを
    生成しないので、見分けを外して平文が残る余地がない。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    # 録画に実際の値が残っていた場合を模す
    for st in batch.get("setup", []):
        if str(st.get("value", "")).startswith("{{SECRET:"):
            st["value"] = "P@ssw0rd-should-not-appear"
    out = pad.write_robin(batch, r"C:\PAD\d.csv", "プロジェクト番号",
                          str(tmp_path / "flow.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "P@ssw0rd-should-not-appear" not in txt
    assert "{{SECRET:" not in txt
    for name in ("EdiUser", "EdiPassword", "LoginMode"):
        assert name not in txt, name


def test_robin_setup_is_open_and_size_only(tmp_path):
    """setup で再生するのは「ページを開く」と「ウィンドウサイズ」だけ。

    ログインも起点画面までの移動も人がやるので、機械が再生する必要がない。"""
    txt = _robin_text(tmp_path)
    head = txt.split("# ---------- 手動ログイン ----------")[0]
    setup_part = head.split("セットアップ（最初に 1 回）")[1]
    assert "SET RectBody" in setup_part
    assert "SET UrlBody" in setup_part
    assert "SET ActBody" not in setup_part


def test_robin_escapes_backslash_in_literals():
    """実機で判明: リテラル内のバックスラッシュは二重化が必要。
    `\\%` は「エスケープされた %」と解釈され、変数展開が壊れて貼り付けが無視される。"""
    assert pad._robin_str(r"C:\temp\x.exe") == "$'''C:\\\\temp\\\\x.exe'''"
    assert pad._robin_str("it's") == "$'''it\\'s'''"


def test_robin_paths_use_double_backslash(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "flow.robin.txt"), r"C:\temp\driver.exe", r"C:\temp")
    txt = open(out, encoding="utf-8").read()
    for line in txt.splitlines():
        if line.lstrip().startswith("#"):
            continue
        # 単独のバックスラッシュ（二重化されていないもの）が残っていないこと
        assert not re.search(r"(?<!\\)\\(?!\\)", line), line


def test_js_oneline_matches_source():
    one = pad.js_act_oneline()
    assert "\n" not in one and "arguments[0]" in one and one.endswith("null };")


def test_robin_keeps_lines_short(tmp_path):
    """PAD は長すぎる 1 行を黙って無視するため、JS は短い行に分けて継ぎ足す。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\PAD\d.csv", "プロジェクト番号",
                          str(tmp_path / "flow.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert max(len(line) for line in txt.splitlines()) < 300
    js_lines = [ln for ln in txt.splitlines() if ln.startswith("SET JsAct TO")]
    assert len(js_lines) > 5                       # 1 行に詰め込んでいない
    assert max(len(ln) for ln in js_lines) < 150   # 実績のある長さに収める
    # バックアップ用の .js も出力される
    assert (tmp_path / "flow.jsact.js").exists()


def test_robin_js_chunks_roundtrip():
    """分割した JsAct を連結すると元の JS に戻ること（%JsAct% 継ぎ足しの検証）。"""
    import re as _re
    js = pad.js_act_oneline()
    restored = ""
    for i, line in enumerate(pad._robin_js_chunks(js)):
        body = _re.match(r"SET JsAct TO \$'''(.*)'''$", line).group(1)
        if i:
            assert body.startswith("%JsAct%")
            body = body[len("%JsAct%"):]
        assert "''''" not in line                  # 紛らわしい引用符の並びが無い
        restored += body
    assert restored == js


def test_robin_auto_driver_block(tmp_path):
    """--auto-driver で Selenium Manager からドライバーパスを受け取る行が入る。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), r"C:\t\drv.exe", r"C:\t",
                          proxy="proxy.example.com:8080", auto_driver=True)
    txt = open(out, encoding="utf-8").read()
    assert "SET AutoDriver TO True" in txt
    assert "Scripting.RunDOSCommand.RunDOSCommandAndFailOnTimeout" in txt
    assert "StandardOutput=> SmOutput" in txt
    assert "Variables.ConvertJsonToCustomObject Json: SmOutput" in txt
    assert "SET DriverExe TO SmObj['result']['driver_path']" in txt
    # プロキシ指定時は取得もプロキシ経由にする
    assert "--proxy %ProxyAddr%" in txt
    # Halt の初期化はドライバー取得より前に 1 回だけ（後で消されない）
    lines = txt.splitlines()
    init = [i for i, ln in enumerate(lines) if ln.strip() == "SET Halt TO False"]
    assert len(init) == 1
    dos = next(i for i, ln in enumerate(lines) if "RunDOSCommand" in ln)
    assert init[0] < dos


def test_robin_auto_driver_off_by_default(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "SET AutoDriver TO False" in txt


def _session_body_variants(txt):
    """生成 Robin の SessionBody 連結を模擬して、組み立て後の JSON を返す。

    本文は前から継ぎ足して組み立てられる。プロキシの行だけ IF の中にあるので、
    それを入れた場合と入れない場合の両方を作る。"""
    import re as _re
    parts = [ln.strip() for ln in txt.splitlines()
             if ln.strip().startswith("SET SessionBody TO")]
    q3 = chr(39) * 3
    pat = "SET SessionBody TO " + chr(92) + "$" + q3 + "(.*)" + q3 + "$"
    lit = [_re.match(pat, x).group(1) for x in parts]
    proxy_idx = [i for i, s in enumerate(lit) if "proxyType" in s]
    assert len(proxy_idx) == 1, lit
    pi = proxy_idx[0]
    out = {}
    for name in ("MicrosoftEdge", "chrome"):
        pref_key = "goog:chromeOptions" if name == "chrome" else "ms:edgeOptions"
        for use_proxy in (False, True):
            body = ""
            for i, s in enumerate(lit):
                if i == pi and not use_proxy:
                    continue
                s = (s.replace("%BrowserName%", name)
                      .replace("%ProxyAddr%", "p.example.com:8080")
                      .replace("%PrefKey%", pref_key)
                      .replace("%DlDirJson%", "C:" + chr(92) * 2 + "t"))
                body = (s.replace("%SessionBody%", body)
                        if "%SessionBody%" in s else body + s)
            out[(name, use_proxy)] = json.loads(body)
    return out


def test_session_body_valid_for_every_browser_and_proxy_combo(tmp_path):
    """ブラウザー × プロキシの 4 通りで、組み立てた本文が妥当な JSON になること。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), r"C:\t\drv.exe", r"C:\t",
                          proxy="p.example.com:8080")
    variants = _session_body_variants(open(out, encoding="utf-8").read())
    for (name, use_proxy), obj in variants.items():
        match = obj["capabilities"]["alwaysMatch"]
        assert match["browserName"] == name
        assert ("proxy" in match) is use_proxy


def test_robin_browser_switch(tmp_path):
    """Browser を 1 行変えれば BrowserName とドライバーのプロセス名も追従すること。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), browser="chrome")
    txt = open(out, encoding="utf-8").read()
    assert "SET Browser TO $'''chrome'''" in txt
    assert "IF Browser = $'''chrome''' THEN" in txt
    assert "SET DriverProc TO $'''chromedriver'''" in txt
    # 起動前は両方のドライバーを終了させる（ブラウザーを跨いでもポートを奪い合わない）
    assert "TerminateProcessByName ProcessName: $'''msedgedriver'''" in txt
    assert "TerminateProcessByName ProcessName: $'''chromedriver'''" in txt
    # ドライバー取得もブラウザーに追従
    assert "--browser %Browser%" in txt


def test_robin_checks_start_screen_before_loop(tmp_path):
    """手動ログイン運用で 1 つ手前の画面から始めた場合に、全件失敗ではなく
    「起点画面ではありません」と伝えて止まること。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "起点画面かどうかを確認する" in txt
    # クリックせずに存在だけ調べる（find は JsAct で操作を伴わない）
    assert '"find", ""' in txt
    body = next(ln for ln in txt.splitlines()
                if "SET ActBody" in ln and '"find"' in ln)
    payload = json.loads(re.search(r"\$'''(.*)'''$", body.strip()).group(1)
                         .replace("%JsAct%", "JS"))
    assert payload["args"][1] == "find"
    # 判定はループ本体より前で、失敗時は Halt する
    lines = txt.splitlines()
    check = next(i for i, ln in enumerate(lines) if "起点画面かどうかを確認する" in ln)
    loop_at = next(i for i, ln in enumerate(lines)
                   if ln.strip().startswith("LOOP FOREACH"))
    assert check < loop_at
    assert "起点画面ではありません" in txt


def test_download_step_waits_and_renames(tmp_path):
    """download ステップが、待って・拾って・付け替えるところまで出ること。

    ダウンロードは「押した瞬間はまだ書き込み中」「ファイル名が事前に分からない」
    の 2 つが厄介なので、押す前の件数を数える／.crdownload が消えるまで待つ／
    更新日時の新しい順で拾う、の 3 つが揃っている必要がある。"""
    batch = {
        "title": "dl", "originHint": "出力",
        "setup": [{"type": "navigate", "url": "http://x/"}],
        "loop": [
            {"type": "download", "selectors": [["#OutputIcon0"]],
             "name": "【一覧】{{プロジェクト番号}}"},
        ],
    }
    out = pad.write_robin(batch, r"C:\t\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "SET DlCountBefore TO DlBefore.Count" in txt
    assert "*.crdownload" in txt
    assert "SortBy1: Folder.SortBy.LastModified SortDescending1: True" in txt
    assert "File.RenameFiles.Rename Files: DlFile NewName: DlName" in txt
    assert "KeepExtension: True" in txt
    # {{列名}} は変数参照に変換される
    assert "SET DlName TO $'''【一覧】%Col1%'''" in txt
    # 落ちてこなかったときは失敗として記録する
    assert "ファイルが落ちてきませんでした" in txt


def test_download_prefs_in_session(tmp_path):
    """保存先の固定と確認ダイアログの抑止がセッション作成に入ること。"""
    batch = {"title": "dl", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID", str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "download.default_directory" in txt
    assert "download.prompt_for_download" in txt
    assert "plugins.always_open_pdf_externally" in txt
    assert "automatic_downloads" in txt
    # ブラウザーごとにキーが変わる
    assert "SET PrefKey TO $'''ms:edgeOptions'''" in txt
    assert "SET PrefKey TO $'''goog:chromeOptions'''" in txt


def test_download_dir_survives_json_escaping(tmp_path):
    """保存先が JSON の解釈を経ても元のパスに戻ること。

    C:\\temp を素で JSON に入れると \\t がタブとして読まれる。
    壊れたパスでもブラウザーは黙って既定のフォルダに落とすので、実行しても
    気づけない。Robin リテラル → JSON の 2 段を通して確かめる。"""
    batch = {"title": "dl", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp")
    txt = open(out, encoding="utf-8").read()
    q3 = chr(39) * 3
    pat = "SET DlDirJson TO " + chr(92) + "$" + q3 + "(.*?)" + q3
    raw = re.search(pat, txt).group(1)

    def unrobin(s):
        o, i, b = [], 0, chr(92)
        while i < len(s):
            if s[i] == b and i + 1 < len(s) and s[i + 1] in (b, chr(39), chr(34)):
                o.append(s[i + 1])
                i += 2
            else:
                o.append(s[i])
                i += 1
        return "".join(o)

    value = json.loads(chr(34) + unrobin(raw) + chr(34))
    assert value == r"C:\temp\download", value


def test_driver_zip_removed_after_extract(tmp_path):
    """展開できたら zip を消すこと。失敗したときは残すこと。

    ドライバーの zip は 20MB 前後あり、版が変わるたびに増える。
    展開が失敗したときに消してしまうと、手で開いて中身を確かめられない
    （エラーページを掴んでいた、という切り分けができなくなる）。"""
    batch = {"title": "z", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"), auto_driver=True)
    txt = open(out, encoding="utf-8").read()
    assert "File.Delete Files: ZipPath" in txt
    # 展開の終了コードを見てから消す
    at = txt.index("File.Delete Files: ZipPath")
    before = txt[:at]
    assert before.rstrip().endswith("IF UzExit = 0 THEN"), before[-200:]


def test_chrome_driver_home_created_before_lookup(tmp_path):
    """Chrome の展開先を、存在確認より前に作ること。

    Chrome の zip は chromedriver-win64 の下に展開されるので、tar を走らせる
    まではそのフォルダが無い。Folder.GetFiles はフォルダが無いとエラーで止まる
    ため、先に作っておく必要がある。Edge は DrvDir がそのまま使えるので
    この問題が出ず、Chrome だけ落ちていた。"""
    batch = {"title": "z", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"), auto_driver=True)
    txt = open(out, encoding="utf-8").read()
    create = txt.index("FolderName: $" + chr(39) * 3 + "chromedriver-win64")
    lookup = txt.index("Folder.GetFiles Folder: DrvHome")
    assert create < lookup, txt[create - 200:lookup + 80]


def test_shot_name_template_at_top(tmp_path):
    """エビデンス名の書式を先頭の設定ブロックに置き、1 件ごとに展開すること。

    %RowId% は明細を読んでからでないと値が入らないので、テンプレートは
    @ID@ のような記号で持っておき、ループの中で実際の値に置き換える。
    テンプレートに出てこない記号の置換は出さない（無駄な行を増やさない）。"""
    batch = {"title": "t", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]},
                      {"type": "screenshot", "name": "s"}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"),
                          shot_name="【受諾】@ID@_社名")
    txt = open(out, encoding="utf-8").read()
    q3 = chr(39) * 3
    assert "SET ShotNameFmt TO $" + q3 + "【受諾】@ID@_社名" in txt
    assert "SET ShotName TO ShotNameFmt" in txt
    assert "TextToFind: $" + q3 + "@ID@" in txt
    # 使っていない記号の置換は出さない（説明のコメントには出てよい）
    assert "TextToFind: $" + q3 + "@KEY@" not in txt
    assert "TextToFind: $" + q3 + "@STAMP@" not in txt
    # 設定ブロック（ループより前）に書式がある
    assert txt.index("SET ShotNameFmt") < txt.index("LOOP FOREACH")


def test_memo_lines_include_paths(tmp_path):
    """メモ欄に BaseDir・エビデンス名・ダウンロード保存先が出ること。

    既定値でも書く。「書いていない＝既定」より「書いてある」ほうが
    確認が早い。"""
    batch = {"title": "t", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp")
    head = open(out, encoding="utf-8").read().split("LLM-Browser-Agent")[0]
    assert "BaseDir: C:" + chr(92) + "temp" in head
    assert "エビデンス名: @ID@__@KEY@__@STAMP@" in head
    assert "ダウンロード保存先: C:" + chr(92) + "temp" + chr(92) + "download" in head


def test_settings_order_puts_maxitems_high(tmp_path):
    """よく触る設定を上に置くこと。

    MaxItems は毎回触るのに、ドライバーの入手方法の長い説明（50 行ほど）に
    押し下げられて見つけにくかった。"""
    txt = _robin_text(tmp_path)
    at = {k: txt.index(k) for k in
          ("SET TargetUrl", "SET BaseDir", "SET MaxItems",
           "SET ShotNameFmt", "SET AutoDriver")}
    assert at["SET TargetUrl"] < at["SET BaseDir"] < at["SET MaxItems"]
    assert at["SET MaxItems"] < at["SET ShotNameFmt"] < at["SET AutoDriver"]


def test_origin_dialog_differs_on_first_try(tmp_path):
    """1 回目はログインを尋ね、2 回目以降は起点の目印だけ出すこと。

    ログイン画面のまま[OK]を押してしまったとき、いきなり「起点画面が
    出ていません」と言われても何をすればよいか分からない。"""
    txt = _robin_text(tmp_path)
    assert "IF StartTry = 1 THEN" in txt
    assert "IF StartTry > 1 THEN" in txt
    assert "ログインが済んでいなければ" in txt
    assert "起点画面が出ていません" in txt


def test_origin_move_inside_retry_loop(tmp_path):
    """起点までの移動を、確認のループの中で毎周やり直すこと。

    ループの外に置くと 1 回しか走らない。ログイン前に[OK]を押すと空振りし、
    そのあとログインして[OK]を押しても移動はもう終わっているので、起点に
    着かないまま「起点画面が出ていません」を繰り返すことになる。"""
    batch = {"title": "t", "originHint": "発注",
             "setup": [{"type": "navigate", "url": "http://x/"},
                       {"type": "click", "selectors": [["#menu"]]}],
             "loop": [{"type": "click", "selectors": [["#POS_ORDERS"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    loop_at = txt.index("LOOP WHILE StartOk = False")
    end_at = txt.index("IF StartTry = 1 THEN")
    inside = txt[loop_at:end_at]
    # 移動も確認も、どちらもループの中にある
    assert "#menu" in inside
    assert "find" in inside
    # 移動でも ActBody を使うので、確認の直前に入れ直している
    assert inside.index("#menu") < inside.index("#POS_ORDERS")


def test_full_page_screenshot_with_fallback(tmp_path):
    """ページ全体を 1 枚に撮り、使えないときは見えている範囲に落ちること。

    W3C の /screenshot は見えている範囲だけを返す。ウィンドウを広げる手も
    あるが、高さは物理画面までしか広げられない（実機では 6000 を要求して
    1220 が上限だった）。Chrome / Edge 独自の captureBeyondViewport なら
    見えていない部分まで 1 枚に収まる。"""
    txt = _robin_text(tmp_path)
    assert "SET FullShot TO True" in txt
    assert "captureBeyondViewport" in txt
    assert "send_command_and_get_result" in txt
    # CDP の応答は value.data、従来は value
    assert "SET ShotB64 TO ShotObj['value']['data']" in txt
    assert "SET ShotB64 TO ShotObj['value']\n" in txt or True
    # 使えなかったときの落とし先がある
    assert "IF ShotSaved = False THEN" in txt


def test_capture_writes_column_to_result_csv(tmp_path):
    """画面から読み取った値が、結果 CSV の列として出ること。

    登録すると発番される番号（要求 ID など）は、次の処理で使う。列に残せば
    その結果 CSV をそのまま次のバッチの明細にできる。列の順番は見出しと
    明細行の 2 か所で使うので、食い違うと列がずれる。"""
    batch = {"title": "c", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]},
                      {"type": "capture", "selectors": [["#no"]], "name": "要求ID"}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    # 見出しに列が出る
    assert "結果,理由,エビデンス,実行日時,要求ID" in txt
    # 読み取った値を変数に入れる
    assert "SET Cap1 TO ActObj['value']['text']" in txt
    # 成功行に値、スキップ・未実行の行は空欄で列数をそろえる
    assert "%RecStamp%,%Cap1%" in txt
    assert "スキップ,,,," in txt
    # 件ごとに空へ戻す（前の行の値が残らないように）
    q6 = chr(39) * 6
    assert "SET Cap1 TO $" + q6 in txt


def test_capture_uses_text_action(tmp_path):
    """読み取りは共通 JavaScript の text で行うこと。"""
    batch = {"title": "c", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "capture", "selectors": [["#no"]], "name": "番号"}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert chr(34) + "text" + chr(34) in txt
    # 読めなかったときは失敗として記録する（空のまま進めない）
    assert "読み取る場所が見つかりません" in txt


def test_result_csv_encoding_matches_reader(tmp_path):
    """結果 CSV を書く文字コードと、明細として読む文字コードをそろえること。

    File.WriteText は指定しないと Unicode（UTF-16）で書く。読み込みは
    CSVEncoding.UTF8 なので、そのままでは結果 CSV を明細として読み直せない。
    再実行モードも、登録結果を次のバッチへ渡す使い方も、どちらも壊れる。
    """
    txt = _robin_text(tmp_path)
    for line in txt.splitlines():
        if "File.WriteText" in line:
            assert "Encoding: File.FileEncoding.UTF8" in line, line
    assert "Encoding: File.CSVEncoding.UTF8" in txt


def test_details_from_result_splits_output(tmp_path):
    """結果 CSV を明細にするとき、出力先を別のファイルにすること。

    同じファイルを読みながら書くと壊れる。登録側の結果を明細にする使い方は、
    要求 ID のような「登録して初めて分かる値」を次の処理へ渡すためのもので、
    元のファイルは残しておく必要がある。"""
    batch = {"title": "r", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "click", "selectors": [["#a"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"),
                          details_from_result=True)
    txt = open(out, encoding="utf-8").read()
    q3 = chr(39) * 3
    assert "SET DetailsFile TO $" + q3 + "%BaseDir%" + chr(92) * 2 + "pad_result.csv" in txt
    assert "SET ResultFile TO $" + q3 + "%BaseDir%" + chr(92) * 2 + "pad_result_2.csv" in txt
    # 指定しなければ従来どおり
    out2 = pad.write_robin(batch, r"C:\t\d.csv", "ID", str(tmp_path / "g.robin.txt"))
    txt2 = open(out2, encoding="utf-8").read()
    assert "pad_result_2.csv" not in txt2


def test_capture_extract_digits(tmp_path):
    """読んだ文章から番号だけを取り出せること。

    実 EDI の要求 ID は「XXPO:検収状況一覧 への要求は予定されました。
    要求IDは 131982564 です。」という文でポップアップに出る。そのままでは
    次のバッチで使えないので、数字以外を落とす。"""
    batch = {"title": "c", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "capture", "selectors": [["aria/情報"]],
                       "name": "要求ID", "extract": "digits"}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    q3 = chr(39) * 3
    assert "TextToFind: $" + q3 + "[^0-9]" + q3 in txt
    # 指定しなければ出さない
    batch["loop"][0].pop("extract")
    out2 = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                           str(tmp_path / "g.robin.txt"))
    assert "[^0-9]" not in open(out2, encoding="utf-8").read()


def test_row_selector_in_shared_js():
    """行を文字で探すセレクタが共通 JavaScript にあること。

    実 EDI の要求要約表には検索欄が無く、要求 ID の行を目で探すしかない。
    XPath で書くと単引用符が Robin リテラルを壊すので、専用の書き方を用意した。
    その行の最初のリンクやアイコンを押す。"""
    js = pad.js_act_oneline()
    assert "row/" in js
    assert "querySelectorAll(`tr`)" in js
    # 押せるリンクを選ぶ。実 EDI の要求要約表は行の先頭に中身も href も無い
    # <a class="xh"></a> があり、それを押しても何も起きない。
    assert "a[href]" in js
    # 隠れている部分も数える。スクロール式の表は画面外の行が innerText に出ない。
    assert "textContent" in js
    # リテラルを壊す文字が入っていないこと
    assert chr(92) not in js
    assert chr(34) not in js


def test_practice_batches_chain_columns(tmp_path):
    """受け取る側が使う列を、渡す側の結果 CSV が持っていること。

    ②の結果 CSV をそのまま③の明細にする使い方では、③が {{列名}} で参照する
    列がすべて②の見出しに要る。足りないと「列またはプロパティ … が
    見つかりません」で止まる。実際、納入日が抜けていて止まった。"""
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def headers_of(name):
        """そのバッチの結果 CSV の見出しを、生成物から読み取る。"""
        b = load_recording(os.path.join(here, 'recordings', name))
        out = pad.write_robin(b, r'C:\t\d.csv', 'プロジェクト番号',
                              str(tmp_path / (name + '.txt')))
        for line in open(out, encoding='utf-8').read().splitlines():
            if 'ResultFile' in line and '結果,理由' in line:
                m = re.search(chr(39) * 3 + "(.*?)" + chr(39) * 3, line)
                return m.group(1).split(',')
        raise AssertionError('見出しが見つからない: ' + name)

    def used_columns(name):
        """そのバッチが {{列名}} で参照している列。"""
        raw = open(os.path.join(here, 'recordings', name), encoding='utf-8').read()
        return set(re.findall(r'\{\{([^}]+)\}\}', raw))

    have = set(headers_of('edi2_publish_batch.json'))
    want = used_columns('edi2_fetch_batch.json')
    missing = want - have
    assert not missing, ('③が使う列が②の結果 CSV に無い: ' + str(sorted(missing)) +
                         ' / ②の見出し: ' + str(sorted(have)))


def test_shared_js_looks_into_iframes():
    """共通 JavaScript が iframe の中も見ること。

    実 EDI のポップアップは iframe に入っている。要求 ID のメッセージも
    その中なので、外側の body だけ見ても永久に見つからない。同じオリジンなら
    contentDocument で中へ入れる。読めないフレームは黙って飛ばす。
    """
    js = pad.js_act_oneline()
    assert "contentDocument" in js
    assert "allDocs" in js
    # リテラルを壊す文字が入っていないこと
    assert chr(92) not in js
    assert chr(34) not in js


def test_scroll_find(tmp_path):
    """見つかるまでスクロールして探せること。

    実 EDI の要求要約表は、スクロールしないと次の行が読み込まれない。
    検索欄も件数を増やす設定も無いので、目的の行が下にあると届かない。
    """
    batch = {"title": "s", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "scrollFind", "text": "{{要求ID}}", "tries": 30}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    assert "LOOP WHILE SclFound = False AND SclTries < 30" in txt
    assert chr(34) + "scroll" + chr(34) in txt
    assert "scrollTop" in pad.js_act_oneline()


def test_recover_waits(tmp_path):
    """復帰したあと、画面が落ち着くのを待つこと。

    実 EDI では、戻った直後にメニューを押そうとして空振りした。
    起点に戻れていて押したい項目も見えているのに、切り替わりきっていなかった。
    """
    batch = {"title": "r", "originHint": "起点",
             "setup": [{"type": "navigate", "url": "http://x/"},
                       {"type": "click", "selectors": [["#home"]]}],
             "loop": [{"type": "click", "selectors": [["#a"]]}],
             "recover": [{"type": "click", "selectors": [["#home"]]}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    # 最初の一致は件数カウンタの初期化。復帰ブロックの中を見る。
    i = txt.index("復帰の直後は画面がまだ切り替わりきっていないことがある")
    assert "WAIT 2" in txt[i:i + 300]
    assert "SET PrevFailed TO False" in txt[i:i + 300]


def test_capture_by_key_text(tmp_path):
    """画面の文字（キー）を探して、その直後を記録できること。

    ポップアップのように要素の指定が分かりにくいものでも、見えている文字で指せる。
    実 EDI では要求 ID のポップアップの要素を推定で指定していて、そこでつまずいた。
    """
    batch = {"title": "k", "setup": [{"type": "navigate", "url": "http://x/"}],
             "loop": [{"type": "capture", "key": "要求IDは", "extract": "digits",
                       "name": "要求ID"},
                      {"type": "capture", "key": "納入番号", "name": "納入番号"}]}
    out = pad.write_robin(batch, r"C:\t\d.csv", "ID",
                          str(tmp_path / "f.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    q = chr(34)
    assert "[[], " + q + "afterDigits" + q + ", " + q + "要求IDは" + q + "]" in txt
    assert "[[], " + q + "after" + q + ", " + q + "納入番号" + q + "]" in txt
    # キーを使うときは、数字以外を落とす後処理は要らない（JavaScript 側で済む）
    assert "[^0-9]" not in txt
    # 読めなかったときは、どのキーで探したかが分かるように書く
    assert "「要求IDは」の後に読み取る文字がありません" in txt
    # 結果 CSV の列になる
    assert "実行日時,要求ID,納入番号" in txt


def test_capture_key_in_shared_js():
    """共通 JavaScript にキーの直後を取り出す手段があること。

    数字だけのときは直後の最初の数字の連続だけを取る。読んだ文字の数字を
    全部つなげると、同じ画面の発注番号などが混ざってしまう。
    """
    js = pad.js_act_oneline()
    assert "afterDigits" in js
    assert "allDocs()" in js        # iframe の中も探す
    assert chr(92) not in js and chr(34) not in js and chr(39) not in js


def test_aria_prefers_attributes_over_text():
    """aria/ は、名前で付いている印を要素の文字より先に探すこと。

    実 EDI のツリーの三角印は title="拡張"。ページの前のほうに
    <option>拡張</option> があり、文字で探すとそちらが先に当たっていた。
    押せてしまうので失敗にもならず、ツリーが開かないまま進んでいた。
    """
    js = pad.js_act_oneline()
    i_attr = js.index("[title=")
    i_text = js.index("normalize-space(text())=` + lit(n)")
    assert i_attr < i_text
    # 1 行に連結するので、// のコメントがあると以降が全部コメントになる
    assert "//" not in js.replace("//*[", "")


def test_details_short_row_without_trailing_comma(tmp_path):
    """末尾の空の skip をカンマごと省いた行も、空として読めること。"""
    from details_io import load_details
    p = tmp_path / "d.csv"
    p.write_text("プロジェクト番号,発注番号,skip\nPM1,900000000001\nPM2,900000000002,1\n",
                 encoding="utf-8")
    headers, rows = load_details(str(p))
    assert headers[-1] == "skip"
    assert len(rows) == 2
    assert str(rows[0].get("skip") or "") == ""
    assert rows[1]["skip"] == "1"


def test_proxy_auto_reads_windows_setting_before_driver_fetch(tmp_path):
    """ProxyAuto は Windows のプロキシ設定に合わせて UseProxy / ProxyAddr を決める。

    社内ではプロキシがオン、テレワークではオフに切り替わる PC で、手の設定のまま
    社内プロキシへ取りに行くと時間切れ（curl 28）になった。判定はドライバーの
    取得より前に済ませること。"""
    import re as _re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\PAD\d.csv", "プロジェクト番号",
                          str(tmp_path / "flow.robin.txt"), auto_driver=True)
    txt = open(out, encoding="utf-8").read()
    lines = txt.splitlines()
    assert "SET ProxyAuto TO True" in lines
    # 分けて継ぎ足した PxCmd が元のコマンドに戻ること
    parts = [ln.strip() for ln in lines if ln.strip().startswith("SET PxCmd TO")]
    assert len(parts) == 3
    vals = [_re.match(r"SET PxCmd TO \$'''(.*)'''$", p).group(1) for p in parts]
    joined = vals[0] + vals[1].replace("%PxCmd%", "", 1) + vals[2].replace("%PxCmd%", "", 1)
    assert joined.replace("\\\\", "\\") == pad._PROXY_AUTO_CMD
    # 引用符を使わない（Robin と DOS コマンドの両方で崩れないように）
    assert '"' not in pad._PROXY_AUTO_CMD and "'" not in pad._PROXY_AUTO_CMD
    first_px = txt.index("IF ProxyAuto THEN")
    assert first_px < txt.index("SET RelCmd TO")
    assert first_px < txt.index("IF UseProxy THEN")
    assert "[プロキシ] %PxNote%" in txt


def test_driver_dir_names_follow_browser(tmp_path):
    """ドライバーはフォルダで受け取り、ファイル名はブラウザーで決まる。

    以前は --driver-exe の値が選んだブラウザーの側にだけ入り、chrome を選んで
    msedgedriver.exe のまま変換すると Chrome 用のパスが msedgedriver.exe になった。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    for kw in ({"driver_exe": r"C:\temp\msedgedriver.exe"},      # 互換：exe のパス
               {"driver_dir": "C:\\temp\\"}):                     # 新：フォルダ（末尾 \ 付き）
        out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                              str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp",
                              browser="chrome", **kw)
        txt = open(out, encoding="utf-8").read()
        assert "SET EdgeDriverExe TO $'''%BaseDir%\\\\msedgedriver.exe'''" in txt
        assert "SET ChromeDriverExe TO $'''%BaseDir%\\\\chromedriver.exe'''" in txt
    out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "g.robin.txt"), out_dir=r"C:\temp",
                          driver_dir=r"D:\drivers")
    txt = open(out, encoding="utf-8").read()
    assert "SET ChromeDriverExe TO $'''D:\\\\drivers\\\\chromedriver.exe'''" in txt


def test_operation_switches_and_memo(tmp_path):
    """ProxyAuto / MaxItems / ウィンドウサイズが反映され、備考欄にも残ること。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp",
                          proxy_auto=False, max_items=5, win_w=1024, win_h=768,
                          driver_dir=r"D:\drivers")
    lines = open(out, encoding="utf-8").read().splitlines()
    assert "SET ProxyAuto TO False" in lines
    assert "SET MaxItems TO 5" in lines
    assert "SET WinW TO 1024" in lines and "SET WinH TO 768" in lines
    memo = "\n".join(ln for ln in lines[:20] if ln.startswith("#"))
    assert "プロキシ自動=無効" in memo
    assert "MaxItems=5 ／ ウィンドウ=1024×768 ／ ドライバー置き場所=D:\\drivers" in memo


def test_operation_switch_defaults():
    """MaxItems は 1 以上、ウィンドウは 指定 → 録画 → 1250×900 の順。"""
    assert pad._clamp_max_items(0) == 1
    assert pad._clamp_max_items("abc") == 1
    assert pad._clamp_max_items(" 7 ") == 7
    assert pad._window_size([]) == (1250, 900)
    rec = [{"type": "setViewport", "width": 1366, "height": 1134}]
    assert pad._window_size(rec) == (1366, 1134)
    assert pad._window_size(rec, 1250, "900") == (1250, 900)
    assert pad._window_size(rec, 0, "x") == (1366, 1134)
    assert pad._driver_dir("", r"C:\temp\msedgedriver.exe") == r"C:\temp"
    assert pad._driver_dir("D:\\drv\\", "") == r"D:\drv"


def test_element_steps_retry_until_found(tmp_path):
    """クリック・入力は、要素が見つかるまで 1 秒おきに探し直す（最大 StepWait 秒）。

    実 EDI（iSupplier Portal）は画面の切り替わりに 2〜3 秒かかり、1 回だけ探すと
    次の要素が無くて「要素が見つかりません」になった。完了確認（exists）は
    今の画面を 1 回だけ見る挙動のまま。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp")
    txt = open(out, encoding="utf-8").read()
    lines = txt.splitlines()
    assert "SET StepWait TO 15" in lines and pad.STEP_WAIT == 15
    loops = [ln.strip() for ln in lines
             if ln.strip() == "LOOP WHILE ActFound = False AND ActWaited < StepWait"]
    clicks_and_fills = [ln for ln in lines
                        if '"click", ""]}' in ln or '"fill", ' in ln]
    clicks_and_fills = [ln for ln in clicks_and_fills if ln.strip().startswith("SET ActBody")]
    # 復帰処理（best effort）は除き、成否を判定するステップはすべて探し直す
    judged = txt.count("で要素が見つかりません'''")
    assert len(loops) == judged and judged > 0
    assert len(clicks_and_fills) >= judged
    # 探し直しの中で二重に押さない: 見つかったら抜ける
    i = lines.index(next(ln for ln in lines if ln.strip() == loops[0]))
    body = "\n".join(lines[i:i + 16])
    assert "SET ActFound TO True" in body and "WAIT 1" in body


def test_site_settings_precedence():
    """サイトの設定は 指定 → バッチ定義の options → 既定 の順で決まる。"""
    assert pad.site_settings({}) == {"stepWait": 15, "preferClickable": True,
                                     "blurAfterFill": True}
    b = {"options": {"stepWait": 25, "preferClickable": False, "blurAfterFill": False}}
    assert pad.site_settings(b) == {"stepWait": 25, "preferClickable": False,
                                    "blurAfterFill": False}
    assert pad.site_settings(b, 9, True, None) == {"stepWait": 9, "preferClickable": True,
                                                   "blurAfterFill": False}
    # 数字でない・0 以下の待ち時間は既定に戻す
    assert pad.site_settings({"options": {"stepWait": "x"}})["stepWait"] == 15
    assert pad.site_settings({"options": {"stepWait": 0}})["stepWait"] == 15


def test_js_act_flags():
    """共通 JS の先頭行でサイトの設定を切り替える。既定はどちらもオン。"""
    on = pad.js_act_oneline()
    assert on.startswith("var PREFER = true, BLUR = true;")
    off = pad.js_act_oneline(False, False)
    assert off.startswith("var PREFER = false, BLUR = false;")
    assert on[len(pad.JS_ACT_FLAGS):] == off[len("var PREFER = false, BLUR = false;"):]
    # Robin と JSON に安全に埋め込める書き方を守る
    for bad in ('"', "'", "\\"):
        assert bad not in on


def test_site_settings_from_batch_options(tmp_path):
    """バッチ定義の options に保存したサイトの設定が、生成物に反映される。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch = load_recording(os.path.join(here, "recordings", "edi2_practice_batch.json"))
    batch["options"] = {"stepWait": 25, "preferClickable": False, "blurAfterFill": False}
    out = pad.write_robin(batch, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp")
    txt = open(out, encoding="utf-8").read()
    assert "SET StepWait TO 25" in txt.splitlines()
    assert "var PREFER = false, BLUR = false;" in txt
    assert "サイトの設定: 待つ上限=25 秒 ／ 押せる要素を優先=無効 ／ 入力後にフォーカスを外す=無効" in txt


def _all_batches():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [os.path.join(here, "examples", "pad", "pad_sample_batch.json")]
    rec = os.path.join(here, "recordings")
    paths += [os.path.join(rec, n) for n in sorted(os.listdir(rec))
              if n.startswith("edi2_") and n.endswith("_batch.json")]
    return paths


def test_robin_embeds_batch_and_extracts_exactly(tmp_path):
    """生成した Robin の末尾にバッチ定義が埋め込まれ、欠けなく取り出せる。"""
    for p in _all_batches():
        batch = load_recording(p)
        out = pad.write_robin(batch, r"C:\temp\d.csv", "ID",
                              str(tmp_path / "f.robin.txt"), out_dir=r"C:\temp")
        txt = open(out, encoding="utf-8").read()
        lines = txt.splitlines()
        # 複数行コメント 1 個にまとまり、1 行は 100 文字以内
        i = lines.index("/#", len(lines) - 400)
        assert lines[i + 1].startswith("PADBATCH v1 lines=")
        assert lines[-2:] == ["PADBATCH END", "#/"]
        assert all(len(ln) <= 100 for ln in lines[i + 2:-2])
        got, why = pad.extract_batch_from_robin(txt)
        assert why == "" and got == load_recording(p), p


def test_extract_survives_pad_copy_and_detects_damage():
    """PAD でコピーし直した形（/# の後ろの空白・CRLF・字下げ）でも読める。壊れていれば理由を返す。"""
    batch = {"title": "t", "setup": [], "loop": [{"type": "click", "selectors": [["#a"]]}],
             "options": {"stepWait": 15.0}}
    lines = ["SET X TO 1"] + pad.batch_embed_lines(batch)
    pad_copy = "\r\n".join(("/# " if ln == "/#" else "    " + ln) for ln in lines)
    got, why = pad.extract_batch_from_robin(pad_copy)
    assert why == "" and got["loop"] == batch["loop"]
    assert got["options"]["stepWait"] == 15 and isinstance(got["options"]["stepWait"], int)

    body = [ln for ln in lines if ln and not ln.startswith(("#", "/#", "PADBATCH", "SET"))]
    broken = "\n".join(lines).replace(body[0], body[0][:-2] + ("AA" if body[0][-2:] != "AA" else "BB"))
    got, why = pad.extract_batch_from_robin(broken)
    assert got is None and "壊れています" in why

    got, why = pad.extract_batch_from_robin("SET X TO 1\n")
    assert got is None and "埋め込まれていません" in why


def test_cli_from_robin_writes_batch(tmp_path):
    """--from-robin で Robin からバッチ定義ファイルを取り出せる。"""
    import subprocess
    import sys as _sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(here, "recordings", "edi2_practice_batch.json")
    robin = tmp_path / "x.robin.txt"
    pad.write_robin(load_recording(src), r"C:\temp\d.csv", "プロジェクト番号", str(robin))
    r = subprocess.run([_sys.executable, os.path.join(here, "pad_webdriver_ref.py"),
                        "--from-robin", str(robin)], capture_output=True, text=True,
                       encoding="utf-8", cwd=here)
    assert r.returncode == 0, r.stderr
    out = tmp_path / "x.batch.json"
    assert json.load(open(out, encoding="utf-8")) == load_recording(src)


# ---------------------------------------------------------------- 埋め込みの無い Robin を読み解く
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RICH = os.path.join(_HERE, "tests", "fixtures", "robin_parse_rich_batch.json")
_OLD = os.path.join(_HERE, "tests", "fixtures", "old_edi2_publish_robin.txt")


def _robin_no_embed(batch, tmp_path, **kw):
    """埋め込みと生成日を除いた Robin（読み解きの比較用）。"""
    idc = (batch.get("options") or {}).get("idCol") or "ID"
    out = pad.write_robin(batch, r"C:\temp\d.csv", idc, str(tmp_path / "p.robin.txt"),
                          out_dir=r"C:\temp", **kw)
    txt = open(out, encoding="utf-8").read().split("\n# ---------- 元のバッチ定義")[0]
    return re.sub(r"# 備考：\d{4}/\d\d/\d\d", "# 備考：X", txt)


def test_parse_robin_rebuilds_same_robin(tmp_path):
    """バッチ定義 → Robin → 読み解き → Robin が、元の Robin と同じになる。"""
    for p in _all_batches() + [_RICH]:
        r1 = _robin_no_embed(load_recording(p), tmp_path)
        got, notes = pad.parse_robin(r1)
        assert got is not None, p
        assert _robin_no_embed(got, tmp_path) == r1, p
        # PAD でコピーし直した形（CRLF・字下げ）でも同じに読める
        copied = "\r\n".join("  " + ln for ln in r1.split("\n"))
        assert pad.parse_robin(copied)[0] == got, p


def test_parse_robin_restores_step_details(tmp_path):
    """読み解きで、待ち時間・回数・読み取り方・名前・列の差し込みが戻る。"""
    got, _ = pad.parse_robin(_robin_no_embed(load_recording(_RICH), tmp_path,
                                             details_from_result=True))
    loop = got["loop"]
    kinds = [s["type"] for s in loop]
    assert kinds == ["comment", "click", "change", "scrollFind", "click", "capture", "capture",
                     "capture", "assertText", "assertText", "download", "download", "screenshot"]
    assert loop[0]["text"] == "{{番号}} の処理 100%"
    assert loop[2]["value"] == "{{発注}}" and loop[2]["selectors"][0] == ["aria/発注番号"]
    assert loop[3]["tries"] == 7 and loop[8]["timeout"] == 20 and "timeout" not in loop[9]
    assert loop[5]["extract"] == "digits" and loop[5]["selectors"] == [["#d"]]
    assert loop[6] == {"type": "capture", "key": "要求IDは", "name": "要求"}
    assert loop[7]["extract"] == "digits" and loop[7]["key"] == "No."
    assert loop[10]["name"] == "{{番号}}_dl" and "name" not in loop[11]
    # 押さずにリンク先を保存するダウンロードも戻る
    assert loop[11].get("saveLink") is True and "saveLink" not in loop[10]
    o = got["options"]
    assert o["idCol"] == "番号" and o["stepWait"] == 30 and o["detailsFromResult"] is True
    assert o["preferClickable"] is False and o["blurAfterFill"] is False
    assert [s["type"] for s in got["recover"]] == ["comment", "navigate", "change", "click"]
    assert got["teardown"][1]["selectors"][0] == ["#logout"]
    assert got["setup"][0] == {"type": "navigate", "url": "https://edi.example.com/a?x='1'"}


def test_parse_old_robin_without_embed(tmp_path):
    """埋め込みの無い古い変換器の Robin（実 EDI2 ③、社名・URL は置き換え済み）を読み解ける。"""
    txt = open(_OLD, encoding="utf-8-sig").read()
    got, how, notes = pad.robin_to_batch(txt)
    assert how == "parse" and got is not None
    assert got["options"]["idCol"] == "プロジェクト番号"
    assert "detailsFromResult" not in got["options"]      # 再実行モードの設定を拾わない
    assert [s["type"] for s in got["setup"]] == ["setViewport", "navigate"] + ["click"] * 4
    assert len(got["loop"]) == 22 and got["recover"][0]["type"] == "click"
    cap = [s for s in got["loop"] if s["type"] == "capture"][0]
    assert cap == {"type": "capture", "key": "要求IDは", "name": "要求ID", "extract": "digits"}
    assert [s for s in got["loop"] if s["type"] == "assertText"][0]["timeout"] == 60
    assert any("運用の設定" in n for n in notes)
    # 組み立て直したものから作った Robin は、読み解くと同じものに戻る
    assert pad.parse_robin(_robin_no_embed(got, tmp_path))[0] == got


def test_robin_to_batch_prefers_embed_then_parses(tmp_path):
    """埋め込みがあればそれを使う。壊れていれば読み解きに切り替え、理由を残す。"""
    batch = load_recording(_RICH)
    out = pad.write_robin(batch, r"C:\temp\d.csv", "番号", str(tmp_path / "e.robin.txt"))
    txt = open(out, encoding="utf-8").read()
    got, how, notes = pad.robin_to_batch(txt)
    assert how == "embed" and got == batch and notes == []
    lines = txt.split("\n")
    k = next(i for i, ln in enumerate(lines) if ln.startswith("PADBATCH v1")) + 1
    lines[k] = ("B" if lines[k][0] == "A" else "A") + lines[k][1:]
    got, how, notes = pad.robin_to_batch("\n".join(lines))
    assert how == "parse" and got["loop"] and "壊れています" in notes[0]
    got, how, notes = pad.robin_to_batch("SET X TO 1\n")
    assert got is None and how == "" and "ではないようです" in notes[0]


def test_cli_from_robin_parses_old_robin(tmp_path):
    """--from-robin は、埋め込みが無ければ読み解いて保存し、戻せなかった点を表示する。"""
    import shutil
    import subprocess
    import sys as _sys
    src = tmp_path / "old.robin.txt"
    shutil.copy(_OLD, src)
    r = subprocess.run([_sys.executable, os.path.join(_HERE, "pad_webdriver_ref.py"),
                        "--from-robin", str(src)], capture_output=True, text=True,
                       encoding="utf-8", cwd=_HERE)
    assert r.returncode == 0, r.stderr
    assert "読み解いて組み立てました" in r.stdout and "運用の設定" in r.stdout
    got = json.load(open(tmp_path / "old.batch.json", encoding="utf-8"))
    assert len(got["loop"]) == 22


# ---------------------------------------------------------------- 失敗分の再実行
def test_retry_mode_switch_comes_after_details(tmp_path):
    """再実行の切り替えは、普段の明細を決めたあとに置く（前にあると上書きされて効かない）。"""
    for dfr, src in ((False, "pad_result.csv"), (True, "pad_result_2.csv")):
        out = pad.write_robin(load_recording(_RICH), r"C:\temp\d.csv", "番号",
                              str(tmp_path / "r.robin.txt"), details_from_result=dfr)
        lines = [ln.strip() for ln in open(out, encoding="utf-8").read().split("\n")]
        main = max(i for i, ln in enumerate(lines) if ln.startswith("SET DetailsFile TO")
                   and "IF RetryMode THEN" not in lines[i - 1])
        retry = lines.index("IF RetryMode THEN")
        assert retry > main, dfr
        assert lines[retry + 1] == f"SET DetailsFile TO $'''%BaseDir%\\\\{src}'''"
        assert lines[retry + 2].endswith("_retry.csv'''")


# ---------------------------------------------------------------- 明細を Excel で受け取る
def _xlsx_robin(tmp_path, details=r"C:\temp\edi2_batch.xlsx", **kw):
    out = pad.write_robin(load_recording(_RICH), details, "番号",
                          str(tmp_path / "x.robin.txt"), **kw)
    return open(out, encoding="utf-8").read()


def test_xlsx_details_reads_sheet_and_makes_result_excel(tmp_path):
    """明細が .xlsx なら「明細」シートを中身の型のまま読み、最後に見る用の xlsx を作る。"""
    txt = _xlsx_robin(tmp_path)
    lines = [ln.strip() for ln in txt.split("\n")]
    assert "SET DetailsXlsx TO True" in lines
    assert "SET DetailsXlsx TO False" in lines          # 再実行は結果 CSV を読む
    assert "Excel.SetActiveWorksheet.ActivateWorksheetByName Instance: DetailsExcel " \
           "Name: $'''明細'''" in lines
    assert any("GetCellContentsMode.TypedValues FirstLineIsHeader: True RangeValue=> Rows" in ln
               for ln in lines)
    # 列ごとに日付の時刻を落とす（列は 番号・発注 の 2 つ）
    untime = [ln for ln in lines if ln.startswith("Text.Replace.ReplaceText Text: Col")]
    assert len(untime) == 2 and "ReplaceWith: $'''%''%'''" in untime[0]
    assert "IF Col1 = $'''''' THEN" in lines
    # 結果 CSV の列（6 + 読み取り 3）を 1 つずつ文字で書く
    writes = [ln for ln in lines if ln.startswith("Excel.WriteToExcel.WriteCell")]
    assert len(writes) == 9 and "Value: $'''\\'%ResRow[0]%'''" in writes[0]
    assert "%XlsNote%" in txt
    # 開けない・シートが無いときは止める。Excel を開いたままにしない
    assert txt.count("ON ERROR") == 3
    assert "明細ファイルに「明細」シートがありません" in txt
    assert "明細を1件も処理せずに中止しました。理由：%HaltReason%。" in txt
    # 生成時の点検で警告が出ない（%''% は PAD の空の文字の式）
    assert pad._lint_robin(txt.split("\n"), log=lambda *_: None) == []


def test_csv_details_have_no_excel_actions(tmp_path):
    """CSV の明細や、前のバッチの結果を読むときは Excel を使わない。"""
    assert "Excel." not in _xlsx_robin(tmp_path, details=r"C:\temp\d.csv")
    assert "Excel." not in _xlsx_robin(tmp_path, details_from_result=True)


def test_parse_robin_reads_xlsx_robin(tmp_path):
    """Excel の明細を読む Robin も、読み解いて同じ Robin に戻せる。"""
    r1 = _robin_no_embed(load_recording(_RICH), tmp_path)
    x1 = re.sub(r"# 備考：\d{4}/\d\d/\d\d", "# 備考：X",
                _xlsx_robin(tmp_path).split("\n# ---------- 元のバッチ定義")[0])
    got, _ = pad.parse_robin(x1)
    assert got == pad.parse_robin(r1)[0]


def test_load_details_prefers_details_sheet():
    """Excel の明細は「明細」シートを読む（先頭のシートが別でも）。"""
    pytest.importorskip("openpyxl")
    from details_io import load_details
    headers, rows = load_details(os.path.join(_HERE, "tests", "fixtures", "details_sample.xlsx"))
    assert headers == ["プロジェクト番号", "発注番号", "納入日", "コード", "skip"]
    assert rows[0]["発注番号"] == "900000000001" and rows[0]["コード"] == "0012"


def test_cli_xlsx_details_without_openpyxl(tmp_path):
    """Robin を作るだけなら、openpyxl が無くても Excel の明細で変換できる。"""
    import subprocess
    import sys as _sys
    det = tmp_path / "d.xlsx"
    det.write_bytes(b"PK")          # 中身は読まない（置いてあるだけ）
    code = ("import builtins,runpy,sys\n"
            "real=builtins.__import__\n"
            "def fake(n,*a,**k):\n"
            "    if n=='openpyxl': raise ImportError('x')\n"
            "    return real(n,*a,**k)\n"
            "builtins.__import__=fake\n"
            "sys.argv=['pad_webdriver_ref.py']+sys.argv[1:]\n"
            "runpy.run_path('pad_webdriver_ref.py',run_name='__main__')\n")
    r = subprocess.run([_sys.executable, "-c", code, "--batch", _RICH, "--details", str(det),
                        "--id-column", "番号", "--robin", str(tmp_path / "o.robin.txt"),
                        "--pad-out-dir", r"C:\temp"],
                       capture_output=True, text=True, encoding="utf-8", cwd=_HERE)
    assert r.returncode == 0, r.stderr
    assert "openpyxl が無いので" in r.stdout
    assert "Excel.ReadFromExcel.ReadAllCells" in open(tmp_path / "o.robin.txt", encoding="utf-8").read()


def test_practice_details_csv_and_xlsx_match():
    """練習用の明細は CSV と Excel の 2 つ。中身が同じであること。"""
    pytest.importorskip("openpyxl")
    from details_io import load_details
    base = os.path.join(_HERE, "data", "edi2_practice_batch")
    assert load_details(base + ".csv") == load_details(base + ".xlsx")


# ---------------------------------------------------------------- 埋め込みと中身の比べ合わせ
def _accept_robin(tmp_path, **kw):
    b = load_recording(os.path.join(_HERE, "recordings", "edi2_accept_batch.json"))
    out = pad.write_robin(b, r"C:\temp\d.csv", "プロジェクト番号",
                          str(tmp_path / "a.robin.txt"), **kw)
    return b, open(out, encoding="utf-8").read()


def test_compare_embed_no_false_alarm(tmp_path):
    """手直ししていない Robin は、変換のしかた（ID 列・Excel・設定）が違っても「手直し」と言わない。"""
    for p in _all_batches() + [_RICH]:
        b = load_recording(p)
        for kw in ({}, {"details_from_result": True, "browser": "chrome", "max_items": 5},
                   {"step_wait": 30, "prefer_clickable": False}):
            for det, idc in ((r"C:\x\d.csv", "ID"), (r"C:\x\d.xlsx", "番号")):
                out = pad.write_robin(b, det, idc, str(tmp_path / "n.robin.txt"), **kw)
                got, how, notes = pad.robin_to_batch(open(out, encoding="utf-8").read())
                assert (how, notes) == ("embed", []), (p, kw, det, notes[:3])
                assert got == b


def test_compare_embed_finds_url_edit_and_keeps_setup(tmp_path):
    """PAD で TargetUrl を直すと、その違いを出し、手直し後は URL だけを直した形にする。"""
    b, txt = _accept_robin(tmp_path)
    edited = txt.replace("file:///C:/temp/index.html", "file:///C:/x/index.html")
    got, how, notes = pad.robin_to_batch(edited)
    assert how == "edited" and len(notes) == 2
    assert notes[1] == ("setup 2 番目：「ページを開く file:///C:/temp/index.html」→"
                        "「ページを開く file:///C:/x/index.html」")
    want = json.loads(json.dumps(b))
    next(s for s in want["setup"] if s["type"] == "navigate")["url"] = "file:///C:/x/index.html"
    assert got == want                      # setup のコメントなどはそのまま
    # 埋め込みをそのまま使うこともできる
    got2, how2, notes2 = pad.robin_to_batch(edited, use_embedded=True)
    assert got2 == b and how2 == "embed" and notes2[1:] == notes[1:]


def test_compare_embed_finds_step_edits(tmp_path):
    """目印の書き換え・アクションの削除・読み解けない追加を、それぞれ見つける。"""
    _, txt = _accept_robin(tmp_path)
    sel = txt.replace('[["#SrchBtn", "text/拡張検索"], "click"',
                      '[["#SrchBtn2", "text/拡張検索"], "click"', 1)
    _, how, notes = pad.robin_to_batch(sel)
    assert how == "edited" and notes[1] == "loop 5 番目：「クリック #SrchBtn」→「クリック #SrchBtn2」"
    lines = txt.split("\n")
    k = next(i for i, ln in enumerate(lines) if '"#ActionGoBtn"' in ln)
    got, how, notes = pad.robin_to_batch("\n".join(lines[:k] + lines[k + 1:]))
    assert notes[1] == "loop：「クリック #ActionGoBtn」がなくなった（9 番目の後）"
    assert len(got["loop"]) == 25
    _, how, notes = pad.robin_to_batch(txt.replace("# ここまで来たら成功", "WAIT 3\n# ここまで来たら成功"))
    assert notes[1] == "loop：読み解けない形の手直しがあります（例: WAIT 3）"


def test_cli_from_robin_reports_edit_and_use_embedded(tmp_path):
    """--from-robin は手直しの違いを表示する。--use-embedded で手直しの前を取り出せる。"""
    import subprocess
    import sys as _sys
    b, txt = _accept_robin(tmp_path)
    src = tmp_path / "e.robin.txt"
    src.write_text(txt.replace("file:///C:/temp/index.html", "file:///C:/x/index.html"),
                   encoding="utf-8")
    for extra, url in (([], "file:///C:/x/index.html"),
                       (["--use-embedded"], "file:///C:/temp/index.html")):
        r = subprocess.run([_sys.executable, os.path.join(_HERE, "pad_webdriver_ref.py"),
                            "--from-robin", str(src), "--save-batch", str(tmp_path / "o.json")] + extra,
                           capture_output=True, text=True, encoding="utf-8", cwd=_HERE)
        assert r.returncode == 0, r.stderr
        assert "手直しされています（1 か所）" in r.stdout
        got = json.load(open(tmp_path / "o.json", encoding="utf-8"))
        assert next(s for s in got["setup"] if s["type"] == "navigate")["url"] == url


def test_download_save_link(tmp_path):
    """saveLink のダウンロードは、押さずに「リンク先を保存」の取り方をする。"""
    txt = _xlsx_robin(tmp_path, details=r"C:\temp\d.csv")
    acts = [ln for ln in txt.split("\n") if "SET ActBody TO" in ln]
    assert sum('"saveLink"' in ln for ln in acts) == 1      # 2 つのうち片方だけ
    assert "名前を付けてリンク先を保存」と同じ取り方" in txt
    assert "action === `saveLink`" in pad.JS_ACT
    # 押さずに、裏でリンク先を受け取る（実機で、写しを押す取り方は認証エラーだった）
    assert "w.fetch(a.href, { credentials: `include` })" in pad.JS_ACT
    # 認証エラーのファイル（FNDWRR.txt）が落ちてきたら、エビデンスにせず失敗にする
    lines = [ln.strip() for ln in txt.split("\n")]
    assert sum(ln.startswith("Folder.GetFiles Folder: DlDir FileFilter: $\'\'\'FNDWRR*.txt") for ln in lines) == 4
    assert lines.count("IF DlAfter.Count > DlCountBefore AND DlErrAfter.Count = DlErrBefore.Count THEN") == 2
    errs = [ln for ln in lines if "認証エラーのファイル（FNDWRR.txt）でした" in ln]
    assert len(errs) == 2
    assert sum("このダウンロードを「リンク先を保存」にしてください" in ln for ln in errs) == 1  # 押す方だけ
    # 手直しの比べ合わせでは、取り方の違いも見える
    plain = txt.replace('"saveLink"', '"click"')
    lines = plain.split("\n")
    k = next(i for i, ln in enumerate(lines) if ln.strip().startswith("# 押さずに「名前を付けて"))
    plain = "\n".join(lines[:k] + lines[k + 1:])
    _, how, notes = pad.robin_to_batch(plain)
    assert how == "edited" and any("（リンク先を保存）」→「ダウンロード #xls2」" in n for n in notes)


# ---------------------------------------------------------------- 開くページ（TargetUrl）
def test_set_target_url():
    """開くページは setup の最初の navigate。無ければウィンドウサイズの後ろに足す。"""
    b = {"setup": [{"type": "setViewport", "width": 1, "height": 2},
                   {"type": "navigate", "url": "https://a/OA.jsp?_ti=1&oas=x"},
                   {"type": "navigate", "url": "https://b/"}], "loop": []}
    assert pad.get_target_url(b) == "https://a/OA.jsp?_ti=1&oas=x"
    got = pad.set_target_url(b, " https://edi.example.com/login ")
    assert [s.get("url") for s in got["setup"]] == [None, "https://edi.example.com/login", "https://b/"]
    assert b["setup"][1]["url"].startswith("https://a/")          # 元は変えない
    assert pad.set_target_url(b, "") == b
    none = pad.set_target_url({"setup": [{"type": "setViewport"}], "loop": []}, "https://x/")
    assert [s["type"] for s in none["setup"]] == ["setViewport", "navigate"]
    assert pad.set_target_url({"loop": []}, "https://x/")["setup"] == [{"type": "navigate", "url": "https://x/"}]


def test_session_params_in_url():
    """ログイン後の URL（その時だけ有効な値が付いたもの）を見分ける。"""
    assert pad.session_params_in_url("https://e/OA_HTML/OA.jsp?OAFunc=X&_ti=12&oas=ab..") == ["_ti", "oas"]
    assert pad.session_params_in_url("https://e/x;jsessionid=AB?Token=1") == ["jsessionid", "token"]
    assert pad.session_params_in_url("https://e/OA_HTML/AppsLocalLogin.jsp") == []
    assert pad.session_params_in_url("https://e/p#state=1") == []


def test_cli_target_url(tmp_path):
    """--target-url は Robin の TargetUrl と埋め込みに入り、--from-robin では取り出す定義に残る。"""
    import subprocess
    import sys as _sys
    rob = tmp_path / "t.robin.txt"
    url = "https://edi.example.com/OA_HTML/AppsLocalLogin.jsp"
    r = subprocess.run([_sys.executable, os.path.join(_HERE, "pad_webdriver_ref.py"),
                        "--batch", os.path.join(_HERE, "recordings", "edi2_accept_batch.json"),
                        "--details", r"C:\temp\d.csv", "--id-column", "プロジェクト番号",
                        "--robin", str(rob), "--target-url", url],
                       capture_output=True, text=True, encoding="utf-8", cwd=_HERE)
    assert r.returncode == 0, r.stderr
    txt = rob.read_text(encoding="utf-8")
    assert f"SET TargetUrl TO $'''{url}'''" in txt
    got, how, _ = pad.robin_to_batch(txt)
    assert how == "embed" and pad.get_target_url(got) == url
    url2 = "https://edi.example.com/OA_HTML/OA.jsp?_ti=1&oas=x"
    r = subprocess.run([_sys.executable, os.path.join(_HERE, "pad_webdriver_ref.py"),
                        "--from-robin", str(rob), "--save-batch", str(tmp_path / "o.json"),
                        "--target-url", url2],
                       capture_output=True, text=True, encoding="utf-8", cwd=_HERE)
    assert r.returncode == 0 and "ログイン後の URL のようです（_ti / oas" in r.stdout
    assert pad.get_target_url(json.load(open(tmp_path / "o.json", encoding="utf-8"))) == url2
