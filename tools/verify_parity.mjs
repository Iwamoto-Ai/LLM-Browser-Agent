// ブラウザ版（tools/pad_converter.html）と Python 版の出力が一致するかを検証する。
// HTML から <script id="pad-core"> を取り出してそのまま実行するので、
// 検証しているのは実際に配布されるコードそのもの。
import fs from "node:fs";
import vm from "node:vm";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

// Python の呼び名は環境で違う（Windows は py、Linux/macOS は python3 が多い）。
// 環境変数 PYTHON があればそれを優先し、無ければ動くほうを探す。
// Windows では py を先に試す。python3 は Microsoft Store の呼び出し口や別のソフトに
// 入っている Python のことがあり、途中で起動に失敗した（spawnSync python3 EACCES）。
const PY = (() => {
  if (process.env.PYTHON) { return process.env.PYTHON; }
  const order = process.platform === "win32" ? ["py", "python", "python3"] : ["python3", "python", "py"];
  for (const cmd of order) {
    try { execFileSync(cmd, ["--version"], { stdio: "pipe" }); return cmd; } catch (e) { /* 次を試す */ }
  }
  console.error("Python が見つかりません。環境変数 PYTHON で指定してください。");
  process.exit(1);
})();

const html = fs.readFileSync("tools/pad_converter.html", "utf8");
const m = html.match(/<script id="pad-core">([\s\S]*?)<\/script>/);
if (!m) { console.error("pad-core スクリプトが見つかりません"); process.exit(1); }
const ctx = { globalThis: null };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(m[1], ctx);
const PadConvert = ctx.PadConvert;

// options にサイトの設定を入れたバッチ定義（Python 版・ブラウザ版の両方が読むこと）
const SITE_BATCH = path.join(os.tmpdir(), "parity_site_batch.json");
{
  const b = JSON.parse(fs.readFileSync("recordings/edi2_practice_batch.json", "utf8")
    .split(/\r?\n/).filter((ln) => !/^\s*(\/\/|#)/.test(ln)).join("\n"));
  b.options = Object.assign({}, b.options || {},
    { stepWait: 25, preferClickable: false, blurAfterFill: false });
  fs.writeFileSync(SITE_BATCH, JSON.stringify(b, null, 2), "utf8");
}

const cases = [
  { batch: "examples/pad/pad_sample_batch.json", idCol: "ID",
    details: "C:\\temp\\sample_batch.csv", browser: "edge" },
  // フレーム型の画面（録画の frame を、そのフレームの中だけで探すのに使う）
  { batch: "recordings/edi_practice_batch.json", idCol: "ID",
    details: "C:\\temp\\edi_batch.csv", browser: "edge", label: "フレーム型" },
  { batch: "recordings/edi2_practice_batch.json", idCol: "プロジェクト番号",
    details: "C:\\temp\\edi2_batch.csv", browser: "chrome" },
  // 既定から外した設定でも一致すること（チェックを外す・件数・大きさ・置き場所）
  { batch: "recordings/edi2_practice_batch.json", idCol: "プロジェクト番号",
    details: "C:\\temp\\edi2_batch.csv", browser: "chrome", label: "既定外の設定",
    py: ["--driver-dir", "D:\\drivers", "--no-auto-driver", "--no-proxy-auto",
         "--max-items", "5", "--win-w", "1024", "--win-h", "768", "--no-show-driver-info"],
    js: { driverDir: "D:\\drivers", autoDriver: false, proxyAuto: false,
          maxItems: "5", winW: "1024", winH: "768", showDriverInfo: false } },
  // サイトの設定を画面（CLI）で指定したとき
  { batch: "recordings/edi2_practice_batch.json", idCol: "プロジェクト番号",
    details: "C:\\temp\\edi2_batch.csv", browser: "edge", label: "サイトの設定を指定",
    py: ["--step-wait", "9", "--no-prefer-clickable", "--no-blur-after-fill"],
    js: { stepWait: "9", preferClickable: false, blurAfterFill: false } },
  // 画面が落ち着くまで待つ（オンのときだけ、各操作の前に待ちが入る）
  { batch: "tests/fixtures/robin_parse_rich_batch.json", idCol: "番号",
    details: "C:\\temp\\d.csv", browser: "edge", label: "画面が落ち着くまで待つ",
    py: ["--wait-idle"], js: { waitIdle: true } },
  // サイトの設定がバッチ定義の options に保存されているとき（どちらも指定しない）
  { batch: SITE_BATCH, idCol: "プロジェクト番号",
    details: "C:\\temp\\edi2_batch.csv", browser: "edge", label: "options のサイトの設定" },
  // 明細が Excel のとき（「明細」シートを読み、最後に結果の Excel を作る）。
  // パスは PC に無い場所にする（あると Python 版が中身を読みに行き、openpyxl の有無に左右される）
  { batch: "tests/fixtures/robin_parse_rich_batch.json", idCol: "番号",
    details: "C:\\parity_no_such_dir\\edi2_batch.xlsx", browser: "edge", label: "明細が Excel" },
];

let ng = 0;
for (const c of cases) {
  const py = path.join(os.tmpdir(), "py.robin.txt");
  execFileSync(PY, ["pad_webdriver_ref.py",
    "--batch", c.batch, "--details", c.details, "--id-column", c.idCol,
    "--robin", py, "--driver-exe", "C:\\temp\\msedgedriver.exe",
    "--pad-out-dir", "C:\\temp", "--pad-browser", c.browser, "--auto-driver"]
    .concat(c.py || []),
    { stdio: "pipe" });

  const t = new Date();
  const out = PadConvert.buildRobin(
    PadConvert.loadRecording(fs.readFileSync(c.batch, "utf8")),
    { detailsPath: c.details, idCol: c.idCol,
      driverExe: "C:\\temp\\msedgedriver.exe", outDir: "C:\\temp",
      proxy: "", autoDriver: true, browser: c.browser,
      today: { y: t.getFullYear(), m: t.getMonth() + 1, d: t.getDate() },
      ...(c.js || {}) });

  // Windows の Python は書き出し時に \n を \r\n に変換する。改行コードの違いは
  // 内容の違いではないので、比較の前にそろえる（CI は Linux なので LF のまま）。
  const nl = (s) => s.split("\r\n").join("\n");
  // 「# 変換器：…」は Python 版とブラウザ版で必ず食い違う（そのための行）。
  // ここだけ比較から外す。他の行は 1 文字も違ってはいけない。
  const strip = (s) => nl(s).split("\n")
    .filter((ln) => !ln.startsWith("# 変換器：")).join("\n");
  const expected = strip(fs.readFileSync(py, "utf8"));
  if (strip(out.robin) === expected) {
    console.log("OK  一致:", c.batch + (c.label ? "（" + c.label + "）" : ""));
  } else {
    ng++;
    console.log("NG  不一致:", c.batch + (c.label ? "（" + c.label + "）" : ""));
    const a = expected.split("\n"), b = strip(out.robin).split("\n");
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
// Robin からバッチ定義を取り出す・読み解く結果も一致すること。
// 埋め込みを外した Robin（古い変換器のもの）は、中身を読み解いて組み立てる。
{
  const robins = [];
  const py = path.join(os.tmpdir(), "py.robin.txt");
  for (const b of ["recordings/edi2_practice_batch.json", "tests/fixtures/robin_parse_rich_batch.json",
                   SITE_BATCH, "recordings/edi_practice_batch.json"]) {
    execFileSync(PY, ["pad_webdriver_ref.py", "--batch", b, "--details", "C:\\temp\\d.csv",
      "--id-column", (PadConvert.loadRecording(fs.readFileSync(b, "utf8")).options || {}).idCol || "ID", "--robin", py,
      "--pad-out-dir", "C:\\temp"], { stdio: "pipe" });
    const txt = fs.readFileSync(py, "utf8");
    robins.push({ name: b + "（埋め込みあり）", text: txt });
    robins.push({ name: b + "（埋め込みなし）",
                  text: txt.split("\n# ---------- 元のバッチ定義")[0] });
    // PAD で手直しした形（URL・目印・アクションの追加）。違いの一覧と手直し後の形も一致すること
    const lines = txt.split("\n");
    // 繰り返しの中の、最後のクリックの目印を書き換える
    const end = lines.findIndex((l) => l.trim() === "# ここまで来たら成功");
    let k = -1;
    lines.forEach((l, i) => { if (i < end && l.indexOf("SET ActBody TO") >= 0 && l.indexOf('"click"') >= 0) { k = i; } });
    const edited = lines.map((l, i) => (i === k ? l.split('[["').join('[["#edited", "') : l))
      .join("\n").split("# ここまで来たら成功").join("WAIT 3\n# ここまで来たら成功")
      .split("SET TargetUrl TO $\'\'\'").join("SET TargetUrl TO $\'\'\'https://edited.example.com/?");
    robins.push({ name: b + "（PAD で手直し）", text: edited, useEmbedded: false });
    robins.push({ name: b + "（PAD で手直し・埋め込みを使う）", text: edited, useEmbedded: true });
  }
  robins.push({ name: "古い Robin", text: fs.readFileSync("tests/fixtures/old_edi2_publish_robin.txt", "utf8") });
  for (const r of robins) {
    const src = path.join(os.tmpdir(), "parity_from.robin.txt");
    const dst = path.join(os.tmpdir(), "parity_from.batch.json");
    fs.writeFileSync(src, r.text, "utf8");
    const pyOut = execFileSync(PY, ["pad_webdriver_ref.py", "--from-robin", src, "--save-batch", dst]
      .concat(r.useEmbedded ? ["--use-embedded"] : []), { stdio: "pipe" }).toString();
    const js = PadConvert.robinToBatch(r.text, !!r.useEmbedded);
    // 違いの一覧も同じであること（Python 版は「  ・」を付けて 1 行ずつ出す）
    const pyNotes = pyOut.split(/\r?\n/).filter((l) => l.indexOf("  ・") === 0).map((l) => l.slice(3));
    const want = JSON.stringify(JSON.parse(fs.readFileSync(dst, "utf8"))) + "\n" + pyNotes.join("\n");
    const got = JSON.stringify(js.batch) + "\n" + js.notes.join("\n");
    if (got === want) { console.log("OK  Robin からの取り出しが一致:", r.name); }
    else { ng++; console.log("NG  Robin からの取り出しが不一致:", r.name + "\n  py: " + want.slice(0, 300) + "\n  js: " + got.slice(0, 300)); }
  }
}
// 開くページ（TargetUrl）の扱いも一致すること
{
  const urls = ["https://e/OA_HTML/OA.jsp?OAFunc=X&_ti=12&oas=ab..", "https://e/x;jsessionid=AB?Token=1",
                "https://e/OA_HTML/AppsLocalLogin.jsp", "https://e/p#state=1", ""];
  const batches = [{ setup: [{ type: "setViewport", width: 1, height: 2 }, { type: "navigate", url: "https://a/" }], loop: [] },
                   { setup: [{ type: "setViewport", width: 1, height: 2 }], loop: [] }, { loop: [] }];
  const js = JSON.stringify({
    s: urls.map((u) => PadConvert.sessionParamsInUrl(u)),
    t: batches.map((b) => PadConvert.setTargetUrl(b, " https://n/ ")),
    g: batches.map((b) => PadConvert.getTargetUrl(b)) });
  const py = execFileSync(PY, ["-c", "import sys,json;sys.path.insert(0,'.');import pad_webdriver_ref as P\n" +
    "u=json.loads(sys.argv[1]);b=json.loads(sys.argv[2])\n" +
    "print(json.dumps({'s':[P.session_params_in_url(x) for x in u],'t':[P.set_target_url(x,' https://n/ ') for x in b]," +
    "'g':[P.get_target_url(x) for x in b]},ensure_ascii=False,separators=(',',':')))",
    JSON.stringify(urls), JSON.stringify(batches)], { stdio: "pipe" }).toString().trim();
  if (js === py) { console.log("OK  開くページ（TargetUrl）の扱いが一致"); }
  else { ng++; console.log("NG  開くページ（TargetUrl）の扱いが不一致\n  py: " + py + "\n  js: " + js); }
}
process.exit(ng ? 1 : 0);
