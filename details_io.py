"""明細ファイル（CSV / xlsx）の読み込み。

変換側（pad_webdriver_ref.py）と実行側（run_batch.py）の両方から使う。
ここに切り出しているのは、変換側がブラウザーエンジンに依存しないようにするため。
run_batch 経由で import すると browser_factory → selenium / playwright まで
たどられ、PyInstaller で EXE 化したときに 80MB 近くまで膨らむ。
"""

from __future__ import annotations

import csv
import datetime as _dt
import sys


def _cell_to_str(v) -> str:
    """Excel 由来の値を安全に文字列化する（900000000001.0 のような事故を防ぐ）。"""
    if v is None:
        return ""
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def load_details(path: str) -> tuple[list[str], list[dict]]:
    """明細ファイル（CSV / xlsx）を読み、(列名リスト, 行 dict のリスト) を返す。"""
    if path.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            sys.exit(".xlsx を直接読むには openpyxl が必要です: pip install openpyxl\n"
                     "（または Excel で『CSV UTF-8』として保存し、その CSV を指定してください）")
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = [_cell_to_str(h) for h in next(it)]
        rows = []
        for r in it:
            if all(v is None or str(v).strip() == "" for v in r):
                continue
            rows.append({h: _cell_to_str(v) for h, v in zip(headers, r) if h})
        return [h for h in headers if h], rows
    # CSV（utf-8-sig で Excel の BOM を吸収）
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = [h.strip() for h in next(reader)]
        except StopIteration:
            sys.exit("明細ファイルが空です: " + path)
        rows = []
        for r in reader:
            if not any(c.strip() for c in r):
                continue
            rows.append({h: c.strip() for h, c in zip(headers, r) if h})
    return [h for h in headers if h], rows
