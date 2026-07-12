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
agent.py — Claude（Anthropic API）でブラウザを操作するエージェントの CLI。

実行ループの実体は agent_core.py にある（Ollama 版と共通）。ここは引数の解釈と
バックエンド選択だけを行う薄いエントリポイント。

使い方:
    python agent.py --task "example.com にログインして 'AI' を検索し結果を保存" \
                    --start-url example.com --no-headless
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from agent_core import run_agent


def run(task: str, start_url: str | None, model: str, max_steps: int,
        headless: bool, out_dir: str, browser_name: str = "edge",
        engine: str = "selenium") -> int:
    """後方互換用エントリポイント（run_template.py から import される）。"""
    return run_agent(task, start_url, model, max_steps, headless, out_dir,
                     browser_name, engine, backend="anthropic")


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="Claude ブラウザ操作エージェント")
    p.add_argument("--task", required=True, help="自然言語のタスク指示")
    p.add_argument("--start-url", default=None, help="開始 URL（任意）")
    p.add_argument("--browser", choices=["edge", "chrome"], default="edge",
                   help="使用ブラウザ（既定: edge）")
    p.add_argument("--engine", choices=["selenium", "playwright"], default="selenium",
                   help="ブラウザ駆動エンジン（既定: selenium）")
    p.add_argument("--model", default="claude-sonnet-4-6",
                   help="使用モデル（既定: claude-sonnet-4-6。難しいタスクは claude-opus-4-8）")
    p.add_argument("--max-steps", type=int, default=25, help="最大ステップ数")
    p.add_argument("--out-dir", default="output", help="スクリーンショット保存先")
    headless = p.add_mutually_exclusive_group()
    headless.add_argument("--headless", dest="headless", action="store_true")
    headless.add_argument("--no-headless", dest="headless", action="store_false")
    p.set_defaults(headless=True)
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY が未設定です（.env か環境変数で設定してください）")

    code = run(args.task, args.start_url, args.model, args.max_steps,
               args.headless, args.out_dir, args.browser, args.engine)
    sys.exit(code)


if __name__ == "__main__":
    main()
