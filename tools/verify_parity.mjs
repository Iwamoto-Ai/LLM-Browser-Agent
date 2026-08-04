// ブラウザ版（tools/pad_converter.html）と Python 版の出力が一致するかを検証する。
// HTML から <script id="pad-core"> を取り出してそのまま実行するので、
// 検証しているのは実際に配布されるコードそのもの。
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";

const html = fs.readFileSync("tools/pad_converter.html", "utf8");
const m = html.match(/<script id="pad-core">([\s\S]*?)<\/script>/);
if (!m) { console.error("pad-core スクリプトが見つかりません"); process.exit(1); }
const ctx = { globalThis: null };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(m[1], ctx);
const PadConvert = ctx.PadConvert;

const cases = [
  { batch: "examples/pad/pad_sample_batch.json", idCol: "ID",
    details: "C:\\temp\\sample_batch.csv", browser: "edge" },
  { batch: "recordings/edi2_practice_batch.json", idCol: "プロジェクト番号",
    details: "C:\\temp\\edi2_batch.csv", browser: "chrome" },
];

let ng = 0;
for (const c of cases) {
  const py = "/tmp/py.robin.txt";
  execFileSync("python3", ["pad_webdriver_ref.py",
    "--batch", c.batch, "--details", c.details, "--id-column", c.idCol,
    "--robin", py, "--driver-exe", "C:\\temp\\msedgedriver.exe",
    "--pad-out-dir", "C:\\temp", "--pad-browser", c.browser, "--auto-driver"],
    { stdio: "pipe" });

  const t = new Date();
  const out = PadConvert.buildRobin(
    PadConvert.loadRecording(fs.readFileSync(c.batch, "utf8")),
    { detailsPath: c.details, idCol: c.idCol,
      driverExe: "C:\\temp\\msedgedriver.exe", outDir: "C:\\temp",
      proxy: "", autoDriver: true, browser: c.browser,
      today: { y: t.getFullYear(), m: t.getMonth() + 1, d: t.getDate() } });

  // Windows の Python は書き出し時に \n を \r\n に変換する。改行コードの違いは
  // 内容の違いではないので、比較の前にそろえる（CI は Linux なので LF のまま）。
  const nl = (s) => s.split("\r\n").join("\n");
  const expected = nl(fs.readFileSync(py, "utf8"));
  if (nl(out.robin) === expected) {
    console.log("OK  一致:", c.batch);
  } else {
    ng++;
    console.log("NG  不一致:", c.batch);
    const a = expected.split("\n"), b = nl(out.robin).split("\n");
    let shown = 0;
    for (let i = 0; i < Math.max(a.length, b.length) && shown < 8; i++) {
      if (a[i] !== b[i]) {
        console.log(`  行${i + 1}\n    py: ${JSON.stringify(a[i])}\n    js: ${JSON.stringify(b[i])}`);
        shown++;
      }
    }
    console.log(`  行数 py=${a.length} js=${b.length}`);
  }
  const jsactPy = nl(fs.readFileSync(py.replace(/\.robin\.txt$/, ".jsact.js"), "utf8"));
  if (jsactPy !== nl(out.jsact)) { ng++; console.log("NG  共通JavaScriptが不一致:", c.batch); }
}
process.exit(ng ? 1 : 0);
