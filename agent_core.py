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

"""
agent_core.py — Anthropic（クラウド）/ Ollama（ローカル）共通のエージェント実行コア。

agent.py / agent_ollama.py は CLI（引数解釈）だけを持ち、実行ループは本モジュールに
一本化されている。ここで提供するもの:

  * run_agent(..., backend="anthropic"|"ollama") … エージェント実行ループ
  * API エラー時の指数バックオフ・リトライ（Anthropic: 429 / 529 / 接続エラー等）
  * 履歴プルーニング … 各ツール結果に付くページ状態 state() は巨大なため、
    直近 N 件（AGENT_KEEP_STATES、既定 3）だけ残して古い state() を省略する。
    ローカル LLM の小さいコンテキストからあふれて「徘徊・同じ操作の繰り返し」が
    起きるのを防ぐ（クラウドでもトークン費用の節約になる）。
  * Ollama の num_ctx 指定 … OLLAMA_NUM_CTX（既定 16384）でコンテキスト長を明示。
    既定値のままだと履歴が黙って切り捨てられ、挙動が不安定になるため。
"""

from __future__ import annotations

import json
import os
import random
import re
import time

from browser_factory import make_browser
from tools import TOOLS, dispatch

# ---------------------------------------------------------------------------
# システムプロンプト
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_ANTHROPIC = """あなたはブラウザを操作する自律エージェントです。WebDriver を介して
実際のブラウザを操作できます。次の方針で行動してください。

- ページ上の操作可能な要素には [番号] が振られています。操作は必ずこの番号で指定します。
- ページ状態が不明なときは get_page_state で確認してから操作します。
- 入力欄の特定 → input_text、ボタン/リンクは click_element を使います。
- セレクトボックス（select）は select_option、チェックボックス/ラジオは set_checked を使います。
  select の選択肢は要素一覧の「選択肢:」に表示されます。
- 表や照会結果など、ページの内容を「読む」必要があるときは get_page_text を使います。
- ログイン時、パスワードなどの秘密情報は値を書かず {{SECRET:NAME}} 形式で指定します
  （実際の値はローカルで補完され、あなたには渡りません）。
- 検索は検索欄に input_text(submit=true) するか、検索ボタンを click します。
- 動的に内容が変わるページでは、必要に応じて get_page_state で取り直します。
- タスクが完了したら take_screenshot で結果を保存し、finish で要約を返します。
- 1 ステップにつき必要なツールだけを呼び、結果を見て次を判断します。"""

SYSTEM_PROMPT_OLLAMA = """あなたはブラウザを操作する自律エージェントです。WebDriver を介して
実際のブラウザを操作します。必ず「ツール」を使って操作を進めてください。

重要な行動ルール:
- navigate・click_element・input_text などの結果には、最新のページ状態（操作可能な
  要素の [番号] 一覧）が自動で付いてきます。したがって get_page_state を繰り返す必要は
  ありません。状態が分かったら、すぐ次の操作（input_text / click_element）を実行します。
- get_page_state を連続で呼ばないこと。状態は直前の結果に必ず含まれています。
- 多くのページは 1 つの画面で完結します。目的の項目が見つからないからといって、別の URL に
  移動したり、やみくもにスクロールして探したりしないこと。まず表示中の要素一覧をよく見ます。
- 指示された項目（例: ユーザーID, パスワード, 交通費）は、要素一覧の各行のラベルと文字列を
  照合し、最も一致する [番号] を選んで操作します。完全一致でなくても部分一致で判断します。
- 操作は必ず要素の [番号] で指定します。座標やセレクタ、URL を推測しないこと。
- 入力欄には input_text、ボタン/リンクには click_element を使います。
- セレクトボックス（select）は select_option、チェックボックス/ラジオは set_checked を使います。
  select の選択肢は要素一覧の「選択肢:」に表示されます。
- パスワード等の秘密情報は値を書かず {{SECRET:NAME}} 形式のまま渡します。
- 値は勝手に変えず、指示された値をそのまま入力します。
- ツール呼び出しは必ず「関数呼び出し（tool call）」として行い、本文に JSON を書かないこと。
- すべて終わったら take_screenshot で保存し、最後に finish を呼んで要約します。
- 1 ステップにつき、次に必要なツールを 1 つだけ呼んでください。
- 安易に finish で諦めないこと。要素一覧に該当しそうな項目があれば、まず操作を試します。"""

# ---------------------------------------------------------------------------
# 履歴プルーニング（古いページ状態の省略）
# ---------------------------------------------------------------------------

_STATE_MARKER = "--- 操作可能な要素 ---"
_PRUNED_NOTE = "（このステップのページ状態は古いため省略。最新の状態は直近の結果を参照）"


def prune_state_text(content: str) -> str:
    """ツール結果テキストから state() 部分を省略する（操作メッセージ行は残す）。"""
    if not isinstance(content, str) or _STATE_MARKER not in content:
        return content
    head = content.split("URL: ", 1)[0].rstrip()
    return (head + "\n" + _PRUNED_NOTE).strip()


def prune_anthropic_history(messages: list, keep: int) -> None:
    """Anthropic 形式の履歴で、直近 keep 件を除くツール結果の state() を省略する。"""
    results = []
    for m in messages:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for block in m["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results.append(block)
    for block in results[:-keep] if keep > 0 else results:
        if isinstance(block.get("content"), str):
            block["content"] = prune_state_text(block["content"])


def prune_ollama_history(messages: list, keep: int) -> None:
    """Ollama 形式の履歴で、直近 keep 件を除くツール結果の state() を省略する。"""
    results = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool" or (
                m.get("role") == "user" and isinstance(m.get("content"), str)
                and m["content"].startswith("[")):
            if isinstance(m.get("content"), str) and _STATE_MARKER in m["content"]:
                results.append(m)
    for m in results[:-keep] if keep > 0 else results:
        m["content"] = prune_state_text(m["content"])


def _keep_states() -> int:
    try:
        return max(1, int(os.environ.get("AGENT_KEEP_STATES", "3")))
    except ValueError:
        return 3


# ---------------------------------------------------------------------------
# Anthropic バックエンド（リトライ付き）
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def _anthropic_chat_with_retry(client, *, max_retries: int = 5, **kwargs):
    """client.messages.create のリトライ付きラッパー。
    レート制限（429）・過負荷（529）・一時的な接続/サーバーエラーを指数バックオフで再試行する。"""
    import anthropic
    for attempt in range(max_retries + 1):
        try:
            return client.messages.create(**kwargs)
        except anthropic.APIConnectionError as e:
            err = e
        except anthropic.APIStatusError as e:
            if e.status_code not in _RETRYABLE_STATUS:
                raise
            err = e
        if attempt >= max_retries:
            raise err
        wait = min(60.0, (2 ** attempt) + random.uniform(0, 1))
        print(f"   ⏳ API エラー（{type(err).__name__}）。{wait:.1f} 秒後にリトライ "
              f"({attempt + 1}/{max_retries}) …")
        time.sleep(wait)


def _run_anthropic(task: str, start_url: str | None, model: str, max_steps: int,
                   browser, out_dir: str) -> int:
    import anthropic
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む

    user_task = task + (f"\n\n開始 URL: {start_url}" if start_url else "")
    messages = [{"role": "user", "content": user_task}]
    exit_code = 1
    keep = _keep_states()

    for step in range(1, max_steps + 1):
        resp = _anthropic_chat_with_retry(
            client, model=model, max_tokens=2048,
            system=SYSTEM_PROMPT_ANTHROPIC, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        finished = False
        for block in resp.content:
            if block.type == "text" and block.text.strip():
                print(f"\n🤖 [{step}] {block.text.strip()}")
            elif block.type == "tool_use":
                print(f"   ⚙️  {block.name}({block.input})")
                result = dispatch(block.name, block.input, browser, out_dir)
                if block.name == "finish" and result == "FINISH":
                    print(f"\n✅ 完了: {block.input.get('summary', '')}")
                    finished = True
                    result = "完了を確認しました。"
                    exit_code = 0
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if finished:
            break
        if not tool_results:
            # ツールを使わずテキストだけ → 終了とみなす
            print("\n（ツール呼び出しがないため終了）")
            exit_code = 0
            break
        messages.append({"role": "user", "content": tool_results})
        prune_anthropic_history(messages, keep)   # 古いページ状態を省略してコンテキストを節約
    else:
        print(f"\n⚠️  上限 {max_steps} ステップに到達しました。")
    return exit_code


# ---------------------------------------------------------------------------
# Ollama バックエンド（ローカル LLM 向けの堅牢化込み）
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TOOL_NAMES = {t["name"] for t in TOOLS}


def _to_ollama_tools(tools: list[dict]) -> list[dict]:
    """Anthropic 形式のツール定義を Ollama / OpenAI 形式に変換する。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _attr(obj, key, default=None):
    """dict でも pydantic オブジェクトでも値を取れるヘルパ。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ollama_chat(client, model, messages, tools):
    """client.chat のラッパ。
    * OLLAMA_NUM_CTX（既定 16384）… コンテキスト長を明示。既定値のままだと履歴が
      黙って切り捨てられ「同じ操作の繰り返し・徘徊」の原因になる。
    * OLLAMA_THINK=0 … 思考オフ（qwen3 等の徘徊抑制に有効）。未対応モデルなら自動で外す。"""
    options = {}
    try:
        options["num_ctx"] = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
    except ValueError:
        pass
    kwargs = dict(model=model, messages=messages, tools=tools)
    if options:
        kwargs["options"] = options
    tv = os.environ.get("OLLAMA_THINK")
    if tv is not None:
        kwargs["think"] = tv.strip().lower() in ("1", "true", "yes", "on")
        try:
            return client.chat(**kwargs)
        except Exception:
            kwargs.pop("think", None)
    try:
        return client.chat(**kwargs)
    except TypeError:
        kwargs.pop("options", None)   # 古い ollama クライアント向けフォールバック
        return client.chat(**kwargs)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _iter_json_objects(text: str):
    """テキスト中から波括弧の対応が取れた {...} を順に取り出す（ネスト対応）。"""
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start:i + 1]
                    start = None


def parse_text_toolcall(text: str):
    """本文に紛れたツール呼び出し JSON を救済して (name, args) を返す。無ければ None。
    例: {"name": "input_text", "arguments": {"index": 3, "text": "demo"}}"""
    if not text:
        return None
    for frag in _iter_json_objects(text):
        try:
            obj = json.loads(frag)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if name in _TOOL_NAMES:
            args = obj.get("arguments")
            if args is None:
                args = obj.get("parameters", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            return name, (args or {})
    return None


def _run_ollama(task: str, start_url: str | None, model: str, max_steps: int,
                browser, out_dir: str) -> int:
    import ollama
    host = os.environ.get("OLLAMA_HOST")
    client = ollama.Client(host=host) if host else ollama.Client()

    user_task = task + (f"\n\n開始 URL: {start_url}" if start_url else "")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_OLLAMA},
        {"role": "user", "content": user_task},
    ]
    tools = _to_ollama_tools(TOOLS)
    exit_code = 1
    keep = _keep_states()

    last_tool = None          # 直前に実行したツール名（連続検知用）
    repeat = 0                # 同一ツールの連続回数
    no_action_nudges = 0      # ツール未使用が続いた回数
    MAX_NUDGE = 3

    def execute(name, args):
        """1 ツールを実行して結果文字列を返す（finish/連続抑制を含む）。"""
        nonlocal exit_code
        print(f"   ⚙️  {name}({args})")
        if name == "finish":
            print(f"\n✅ 完了: {args.get('summary', '')}")
            exit_code = 0
            return "FINISH", True
        return dispatch(name, args, browser, out_dir), False

    for step in range(1, max_steps + 1):
        resp = _ollama_chat(client, model, messages, tools)
        msg = _attr(resp, "message")
        content = _strip_think(_attr(msg, "content", "") or "")
        tool_calls = _attr(msg, "tool_calls") or []
        messages.append(msg if not isinstance(msg, dict) else dict(msg))

        # 1) 構造化された tool_calls があれば実行
        if tool_calls:
            no_action_nudges = 0
            finished = False
            for tc in tool_calls:
                fn = _attr(tc, "function")
                name = _attr(fn, "name")
                args = _attr(fn, "arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                # 同一ツールの無意味な連続（特に get_page_state）を抑制
                repeat = repeat + 1 if name == last_tool else 0
                last_tool = name
                if name == "get_page_state" and repeat >= 1:
                    print(f"   ⚙️  {name}() … 連続のため抑制")
                    messages.append({
                        "role": "tool", "tool_name": name,
                        "content": "ページ状態は直前の結果に含まれています。"
                                   "get_page_state はもう呼ばないでください。"
                                   "input_text か click_element で次の操作を 1 つ実行してください。",
                    })
                    continue

                result, finished = execute(name, args)
                if finished:
                    result = "完了を確認しました。"
                messages.append({"role": "tool", "tool_name": name, "content": result})
            if finished:
                break
            prune_ollama_history(messages, keep)   # 古いページ状態を省略（小コンテキスト対策）
            continue

        # 2) tool_calls が無い → 本文に紛れたツール呼び出しを救済
        if content:
            print(f"\n🤖 [{step}] {content[:300]}")
        salvaged = parse_text_toolcall(content)
        if salvaged:
            name, args = salvaged
            repeat = repeat + 1 if name == last_tool else 0
            last_tool = name
            if name == "get_page_state" and repeat >= 1:
                messages.append({"role": "user",
                                 "content": "状態は取得済みです。input_text か click_element で操作を実行してください。"})
                continue
            result, finished = execute(name, args)
            messages.append({"role": "user", "content": f"[{name} の実行結果]\n{result}"})
            if finished:
                break
            no_action_nudges = 0
            prune_ollama_history(messages, keep)
            continue

        # 3) ツールも JSON も無い → 数回だけ促してから打ち切り
        no_action_nudges += 1
        if no_action_nudges > MAX_NUDGE:
            print("\n（ツールが使われないため終了）")
            exit_code = 0 if last_tool == "finish" else 1
            break
        messages.append({
            "role": "user",
            "content": "手順の説明ではなく、次の操作を必ずツール（input_text / click_element / "
                       "take_screenshot / finish）として 1 つ実行してください。get_page_state は不要です。",
        })
    else:
        print(f"\n⚠️  上限 {max_steps} ステップに到達しました。")
    return exit_code


# ---------------------------------------------------------------------------
# 共通エントリポイント
# ---------------------------------------------------------------------------

def run_agent(task: str, start_url: str | None, model: str, max_steps: int,
              headless: bool, out_dir: str, browser_name: str = "edge",
              engine: str = "selenium", backend: str = "anthropic") -> int:
    """エージェントを 1 タスク実行する（agent.py / agent_ollama.py 共通の実体）。"""
    browser = make_browser(engine, browser_name, headless)
    os.makedirs(out_dir, exist_ok=True)
    try:
        if backend == "ollama":
            return _run_ollama(task, start_url, model, max_steps, browser, out_dir)
        if backend == "anthropic":
            return _run_anthropic(task, start_url, model, max_steps, browser, out_dir)
        raise ValueError(f"未対応のバックエンド: {backend}（anthropic または ollama）")
    except KeyboardInterrupt:
        print("\n中断しました。")
        return 1
    finally:
        browser.quit()
