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
    # 明細の値がセレクタにも展開されている（aria/{{発注番号}} → aria/900000000001）
    execs = [b for m, p, b in _Handler.calls if p.endswith("/execute/sync")]
    assert any("aria/900000000001" in json.dumps(b["args"][0], ensure_ascii=False)
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
