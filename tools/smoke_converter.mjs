// ブラウザ版変換器の画面が実際に初期化できるかを見る。
//
// verify_parity.mjs は <script id="pad-core"> だけを取り出して実行するため、
// 画面側のスクリプト（イベント登録やフッターの版表示）は検証されない。
// 実際、版の定数を IIFE の外から参照してしまい、画面側が ReferenceError で
// 止まってボタンが 1 つも効かない、という不具合を出したことがある。
// 変換そのものが正しくても画面が死ぬので、初期化だけは別に確かめる。
import fs from "node:fs";
import { JSDOM } from "jsdom";

const html = fs.readFileSync("tools/pad_converter.html", "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously" });
dom.window.addEventListener("error", (e) => errors.push(String(e.error || e.message)));
await new Promise((r) => setTimeout(r, 300));

const d = dom.window.document;
for (const id of ["run", "copy", "save", "copyJs", "batchFile", "drop", "ver"]) {
  if (!d.getElementById(id)) { errors.push("要素が無い: #" + id); }
}
// 共通 JavaScript の保存はウイルス対策にブロックされるため、あってはいけない
if (d.getElementById("saveJs")) { errors.push("保存ボタンが残っている: #saveJs"); }

const ver = d.getElementById("ver") ? d.getElementById("ver").textContent : "";
if (!/変換器 .+ v\d+\.\d+\.\d+/.test(ver)) {
  errors.push("版の表示が出ていない: " + JSON.stringify(ver));
}
if (typeof dom.window.PadConvert?.buildRobin !== "function") {
  errors.push("PadConvert が公開されていない");
}

if (errors.length) {
  console.log("NG  ブラウザ版の初期化に失敗\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log("OK  ブラウザ版の初期化に成功:", ver);
