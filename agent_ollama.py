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
agent_ollama.py — ローカル LLM (Ollama) でブラウザを操作するエージェントの CLI。

実行ループの実体は agent_core.py にある（Anthropic 版と共通）。ローカルモデル向けの
堅牢化（同一ツールの連続抑制・本文 JSON の救済・<think> 除去・履歴プルーニング・
OLLAMA_NUM_CTX 指定）も agent_core 側に実装されている。

前提:
  * Ollama 本体が起動していること（既定 http://localhost:11434。OLLAMA_HOST で変更可）
  * tool calling 対応モデルを pull 済み（例: ollama pull qwen3:14b / mistral-nemo）
"""

from __future__ import annotations

import argparse
import sys

from agent_core import run_agent


def run(task: str, start_url: str | None, model: str, max_steps: int,
        headless: bool, out_dir: str, browser_name: str = "edge",
        engine: str = "selenium") -> int:
    """後方互換用エントリポイント（run_template.py から import される）。"""
    return run_agent(task, start_url, model, max_steps, headless, out_dir,
                     browser_name, engine, backend="ollama")


def main() -> None:
    p = argparse.ArgumentParser(description="LLM Browser Agent（ローカル LLM / Ollama 版）")
    p.add_argument("--task", required=True, help="自然言語のタスク指示")
    p.add_argument("--start-url", default=None, help="開始 URL（任意）")
    p.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    p.add_argument("--engine", choices=["selenium", "playwright"], default="selenium",
                   help="ブラウザ駆動エンジン（既定: selenium）")
    p.add_argument("--model", default="qwen3:14b",
                   help="Ollama モデル名（既定: qwen3:14b。tool calling 対応モデルを推奨）")
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument("--out-dir", default="output")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--headless", dest="headless", action="store_true")
    g.add_argument("--no-headless", dest="headless", action="store_false")
    p.set_defaults(headless=True)
    args = p.parse_args()

    code = run(args.task, args.start_url, args.model, args.max_steps,
               args.headless, args.out_dir, args.browser, args.engine)
    sys.exit(code)


if __name__ == "__main__":
    main()
