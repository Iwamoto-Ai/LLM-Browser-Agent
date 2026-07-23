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


def test_robin_keeps_credentials_as_variables(tmp_path):
    txt = _robin_text(tmp_path)
    assert "{{SECRET:" not in txt
    assert "%EdiUser%" in txt and "%EdiPassword%" in txt


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
