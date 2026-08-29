// 練習用のバッチ定義を、練習サイトに対して実際に再生してみる。
//
// バッチ定義と練習サイトは別々に直すので、片方だけ変えると噛み合わなくなる。
// 実際、練習サイトの導線を実 EDI に合わせたとき、ループ途中に残っていた
// 古い戻り方に気づけず「要素が見つかりません」で落ちた。
//
// 要素の探し方は生成物と同じ共通 JavaScript（JS_ACT）を使うので、
// PAD で動かしたときと同じ結果になる。
import fs from "node:fs";
import path from "node:path";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(import.meta.dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "tools/pad_converter.html"), "utf8");
const core = html.match(/<script id="pad-core">([\s\S]*?)<\/script>/)[1];
const ctx = { window: {}, document: {} };
// eslint-disable-next-line no-eval
const vm = await import("node:vm");
vm.createContext(ctx);
vm.runInContext(core, ctx);
const jsAct = ctx.PadConvert.jsAct();

// 明細 CSV の 1 行目を {{列名}} の値に使う
const csv = fs.readFileSync(path.join(ROOT, "data/edi2_practice_batch.csv"), "utf8")
  .replace(/^\uFEFF/, "").trim().split(/\r?\n/);
const cols = csv[0].split(",");
// 明細の 1 行目を使う。capture で書き換わるので、バッチごとに作り直す
// （PAD では結果 CSV を経由して次のバッチへ渡る）。
const baseRow = {};
csv[1].split(",").forEach((v, i) => { baseRow[cols[i]] = v; });
let row = {};
const fill = (s) => String(s === undefined ? "" : s)
  .replace(/\{\{([^}]+)\}\}/g, (_, k) => (row[k] === undefined ? "" : row[k]));

const targets = process.argv.slice(2).length ? process.argv.slice(2) : [
  "recordings/edi2_accept_batch.json",
  "recordings/edi2_delivery_batch.json",
  "recordings/edi2_report_batch.json",
];

let ng = 0;
for (const rel of targets) {
  const batch = ctx.PadConvert.loadRecording(
    fs.readFileSync(path.join(ROOT, rel), "utf8"));
  const site = fs.readFileSync(path.join(ROOT, "test_site/edi2/index.html"), "utf8");
  const dom = new JSDOM(site, { runScripts: "dangerously" });
  const d = dom.window.document;
  // 生成物と同じ共通 JavaScript を、このページの中で使えるようにする
  const act = dom.window.eval("(function(){ return function(a,b,c){" +
    jsAct.replace(/arguments\[0\]/g, "a").replace(/arguments\[1\]/g, "b")
         .replace(/arguments\[2\]/g, "c") + "}; })()");

  // ログインは人がやる部分。ここだけ直接操作する
  d.getElementById("usernameField").value = "demo";
  d.getElementById("passwordField").value = "password123";
  d.getElementById("LoginBtn").dispatchEvent(
    new dom.window.MouseEvent("click", { bubbles: true }));

  const steps = [];
  for (const st of batch.setup || []) {
    if (st.type === "click" || st.type === "doubleClick") { steps.push(["setup", st]); }
  }
  for (const st of batch.loop || []) { steps.push(["loop", st]); }

  row = Object.assign({}, baseRow);
  // ステップ番号は生成物と同じ数え方にする（setup と loop で別々に 1 から）
  const nos = { setup: 0, loop: 0 };
  let failed = null, done = 0;
  for (const [sec, st] of steps) {
    if (st.type === "comment" || st.type === "screenshot") { continue; }
    nos[sec] += 1;
    done += 1;
    const no = nos[sec];
    const cands = (st.selectors || []).map((g) => fill(g[0]));
    let r;
    if (st.type === "capture") {
      // 画面から読み取った値は、後続の {{名前}} に渡る（PAD では結果 CSV 経由）
      r = act(cands, "text", "");
      if (r && r.ok) { row[st.name] = r.text; }
    } else if (st.type === "assertText") {
      r = act([], "exists", fill(st.text));
    } else if (st.type === "change") {
      r = act(cands, "fill", fill(st.value));
    } else {
      r = act(cands, "click", "");
    }
    if (!r || r.ok !== true) {
      failed = `${sec} ステップ${no}（${st.type} ${cands[0] || fill(st.text || "")}）`;
      break;
    }
  }
  if (failed) { ng += 1; console.log("NG  " + rel + " → " + failed + " で要素が見つかりません"); }
  else { console.log("OK  " + rel + " → " + done + " ステップ通過"); }
}
process.exit(ng ? 1 : 0);
