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
for (const id of ["run", "copy", "save", "copyJs", "batchFile", "drop", "ver",
                  "idcol", "idcolHint", "detailsFile"]) {
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

// 振り分け画面の部品が公開されているか
for (const fn of ["isRecording", "usableSteps", "describeStep", "guessAssignments",
                  "buildBatch", "hasCredentials"]) {
  if (typeof dom.window.PadConvert?.[fn] !== "function") {
    errors.push("PadConvert." + fn + " が公開されていない");
  }
}
if (!d.getElementById("assignBox")) { errors.push("振り分け画面が無い: #assignBox"); }
if (!d.getElementById("assignBox").hidden) { errors.push("#assignBox が最初から見えている"); }

// 録画を読ませたときの推測が壊れていないか（最小の録画で確認）
const P = dom.window.PadConvert;
const rec = {
  title: "t",
  steps: [
    { type: "navigate", url: "https://x/" },
    { type: "change", value: "u", selectors: [["aria/ユーザー名"]] },
    { type: "change", value: "p", selectors: [["aria/パスワード"]] },
    { type: "click", selectors: [["aria/ログイン"]] },
    { type: "keyDown", key: "a" },
    { type: "click", selectors: [["aria/ホーム"]] },
    { type: "change", value: "123", selectors: [["#no"]] },
    { type: "click", selectors: [["aria/ホーム"]] }
  ]
};
if (!P.isRecording(rec)) { errors.push("録画として判定されない"); }
const steps = P.usableSteps(rec);
if (steps.length !== 7) { errors.push("keyDown が除外されていない: " + steps.length); }
const as = P.guessAssignments(steps);
// 手動ログイン専用。ログイン欄は「使わない」に倒し、変換に含めない
if (as[1].sec !== "skip" || as[2].sec !== "skip") {
  errors.push("ログイン欄が「使わない」になっていない");
}
if (!P.hasCredentials(rec)) { errors.push("ログイン情報の混入を検出できていない"); }
if (as[steps.length - 1].sec !== "loop+recover") { errors.push("戻る操作を復帰に割り当てていない"); }
as[5].varCol = "発注番号";
as[5].sec = "loop";
const batch = P.buildBatch(steps, as, "t");
if (!batch.loop.length || !batch.recover.length) { errors.push("バッチ定義の組み立てに失敗"); }
const j = JSON.stringify(batch);
if (j.indexOf("{{発注番号}}") < 0) { errors.push("列名の差し込みができていない"); }
if (j.indexOf('"u"') >= 0 || j.indexOf('"p"') >= 0) { errors.push("録画時の実値が残っている"); }

// 背景色を固定したメッセージ欄に文字色が付いているか（ダークモードで白文字になる事故の防止）
const css = [...d.querySelectorAll("style")].map((s) => s.textContent).join("\n");
for (const cls of [".warn", ".err", ".ok"]) {
  const m = new RegExp("\\" + cls + "\\s*\\{[^}]*\\}").exec(css);
  if (!m || !/color:\s*#/.test(m[0].replace(/border-left[^;]*;/, ""))) {
    errors.push(cls + " に文字色の指定が無い（ダークモードで読めなくなる）");
  }
}
if (!/@media\s*\(prefers-color-scheme:\s*dark\)/.test(css)) {
  errors.push("ダークモード用の指定が無い");
}

if (errors.length) {
  console.log("NG  ブラウザ版の初期化に失敗\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log("OK  ブラウザ版の初期化に成功:", ver);
