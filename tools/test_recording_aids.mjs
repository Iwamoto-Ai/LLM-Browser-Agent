// 録画 JSON を「そのまま」変換できるようにする仕掛けの確認。
//
//  1. 同じ目印の要素が複数あるとき、押して動く要素（リンク・ボタン）を選ぶ
//     （Oracle は区画の div とリンクの a に同じ id を付けることがある）
//  2. 入力のあとフォーカスを外す
//  3. 録画の Win+Shift+S をエビデンス撮影にする
//  4. 明細 CSV の 1 行目と同じ値を {{列名}} にする
//
// 3・4 は、実際の納入登録の録画（番号はダミーに置換済み）を手を加えずに通す。
import fs from "node:fs";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const html = fs.readFileSync("tools/pad_converter.html", "utf8");
const core = html.match(/<script id="pad-core">([\s\S]*?)<\/script>/)[1];
const ctx = { globalThis: null };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(core, ctx);
const P = ctx.PadConvert;
const errors = [];
const check = (cond, msg) => { if (!cond) { errors.push(msg); } };

// ---------------------------------------------------------------- 1・2 共通 JS
function runAct(bodyHtml, cands, action, value, prefer = true, blur = true) {
  const dom = new JSDOM("<!doctype html><body>" + bodyHtml + "</body>", { runScripts: "outside-only" });
  const w = dom.window;
  w.__clicked = [];
  w.__ids = [];
  w.document.querySelectorAll("*").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.currentTarget === e.target) { w.__clicked.push(el.tagName); w.__ids.push(el.id); }
    });
  });
  const src = P.jsActOneline(prefer, blur);
  const fn = w.eval("(function () { return function () { " + src + " }; })()");
  const res = fn(cands, action, value);
  return { res, clicked: w.__clicked, ids: w.__ids, w };
}

// Oracle の「納入登録」と同じ形: 区画の div とリンクの a に同じ id
const dup = '<div id="PosCreateAsnLink"><table><tr><td>' +
            '<a id="PosCreateAsnLink" href="#go">納入登録</a></td></tr></table></div>';
{
  const r = runAct(dup, ["#PosCreateAsnLink"], "click", "");
  check(r.res.ok, "重複 id: クリックが失敗した");
  check(r.clicked[0] === "A", "重複 id: リンクではなく " + r.clicked[0] + " を押した");
}
{
  const r = runAct(dup, ["id/PosCreateAsnLink"], "click", "");
  check(r.clicked[0] === "A", "重複 id（id/）: リンクではなく " + r.clicked[0] + " を押した");
}
{
  const r = runAct(dup, ["xpath///*[@id=\"PosCreateAsnLink\"]"], "click", "");
  check(r.clicked[0] === "A", "重複 id（xpath）: リンクではなく " + r.clicked[0] + " を押した");
}
{
  // スイッチを切ると、今までどおり先にある方
  const r = runAct(dup, ["#PosCreateAsnLink"], "click", "", false);
  check(r.clicked[0] === "DIV", "優先を切っても先頭の要素を押していない: " + r.clicked[0]);
}
{
  // 1 つしか無ければ、押せない要素でもそれを押す（今と同じ）
  const r = runAct('<div id="only">x</div>', ["#only"], "click", "");
  check(r.clicked[0] === "DIV", "1 つだけのとき、その要素を押していない");
}
{
  // 先頭がリンクの中の画像なら、今までどおり先頭を押す（Oracle のツリーの三角）。
  // 後ろに onclick 付きの画像があっても、そちらへ乗り換えない。
  const tree = '<div id="MenuRow"><a href="#t"><img id="tri" class="m"></a> 仕入先 ' +
               '<img id="other" class="m" onclick="void 0"></div>';
  const r = runAct(tree, ["#MenuRow img.m"], "click", "");
  check(r.ids[0] === "tri", "リンクの中の先頭の画像ではなく " + r.ids[0] + " を押した");
}
{
  // 先頭がボタンなら先頭（後ろのリンクへ乗り換えない）
  const r = runAct('<button class="k" id="b1">x</button><a class="k" id="a1" href="#">y</a>',
                   [".k"], "click", "");
  check(r.ids[0] === "b1", "先頭のボタンではなく " + r.ids[0] + " を押した");
}
{
  // 入力のあとフォーカスを外す
  const body = '<input id="f"><input id="g">';
  const on = runAct(body, ["#f"], "fill", "abc");
  check(on.w.document.activeElement.id !== "f", "入力のあとフォーカスが残っている");
  check(on.w.document.getElementById("f").value === "abc", "入力されていない");
  const off = runAct(body, ["#f"], "fill", "abc", true, false);
  check(off.w.document.activeElement.id === "f", "外さない設定なのにフォーカスが外れた");
}

// ---------------------------------------------------------------- 3・4 録画の下ごしらえ
const rec = P.loadRecording(fs.readFileSync("tests/fixtures/oracle_asn_recording.json", "utf8"));
const steps = P.usableSteps(rec);
const assigns = P.guessAssignments(steps);

// 3. Win+Shift+S は「発行」のあと（最後の家アイコンの手前）
const shots = P.keyShotAfter(rec);
check(shots.length === 1, "Win+Shift+S の検出数が 1 でない: " + shots.length);
const issued = steps.findIndex((s) => JSON.stringify(s.selectors || []).indexOf("SubmitBtn") >= 0);
check(shots[0] === issued, "Win+Shift+S が「発行」のあとになっていない: " + shots[0] + " / " + issued);
shots.forEach((i) => { assigns[i].shot = true; });

// 4. 明細 CSV の 1 行目
const csv = "プロジェクト番号,発注番号,納入日,skip\nPM9000000001,900000000001,2026/09/01,\n";
const done = P.autoColumnAssign(steps, assigns, P.csvHeaders(csv), P.csvFirstRow(csv));
const cols = done.map((x) => x.col).sort();
check(JSON.stringify(cols) === JSON.stringify(["プロジェクト番号", "発注番号", "納入日"]),
      "列の割り当てが違う: " + JSON.stringify(done));
const left = assigns.filter((a) => a.sec !== "skip" && a.varCol === "?");
check(left.length === 0, "列名が決まらない行が残る: " + left.length);

const batch = P.buildBatch(steps, assigns, rec.title, {});
const loopText = JSON.stringify(batch.loop);
check(loopText.indexOf("{{発注番号}}") >= 0, "発注番号が {{発注番号}} になっていない");
check(loopText.indexOf("{{プロジェクト番号}}") >= 0, "納入番号が {{プロジェクト番号}} になっていない");
check(loopText.indexOf("{{納入日}}") >= 0, "納入日が {{納入日}} になっていない");
check(loopText.indexOf("900000000001") < 0, "録画の発注番号が残っている");
check(batch.loop.some((s) => s.type === "screenshot"), "エビデンス撮影が入っていない");

// 変換まで通ること（既定のサイトの設定で、押せる要素の優先と探し直しが入る）
const out = P.buildRobin(batch, { detailsPath: "C:\\temp\\edi2_batch.csv", idCol: "プロジェクト番号",
  outDir: "C:\\temp", browser: "edge", today: { y: 2026, m: 9, d: 1 } });
check(out.robin.indexOf("var PREFER = true, BLUR = true;") >= 0, "共通 JS にサイトの設定が入っていない");
check(out.robin.indexOf("SET StepWait TO 15") >= 0, "StepWait が入っていない");

// ---------------------------------------------------------------- 5. バッチ定義の埋め込み
{
  for (const f of ["examples/pad/pad_sample_batch.json", "recordings/edi2_practice_batch.json",
                   "recordings/edi2_fetch_batch.json"]) {
    const b = P.loadRecording(fs.readFileSync(f, "utf8"));
    const r = P.buildRobin(b, { detailsPath: "C:\\temp\\d.csv", idCol: "ID", outDir: "C:\\temp",
                                browser: "edge", today: { y: 2026, m: 9, d: 1 } });
    const got = P.extractBatchFromRobin(r.robin);
    check(got.reason === "" && JSON.stringify(got.batch) === JSON.stringify(b),
          "埋め込みから元のバッチ定義に戻らない: " + f + " " + got.reason);
    // PAD でコピーし直した形（/# の後ろの空白・CRLF・字下げ）
    const copied = r.robin.split("\n").map((l) => (l === "/#" ? "/# " : "  " + l)).join("\r\n");
    const got2 = P.extractBatchFromRobin(copied);
    check(got2.batch && JSON.stringify(got2.batch) === JSON.stringify(b), "PAD のコピーから戻らない: " + f);
  }
  // 日本語・絵文字（4 バイト文字）も崩れない
  const odd = { title: "納入登録 📦 テスト", setup: [], loop: [{ type: "comment", text: "{{発注番号}} 100%" }] };
  const back = P.extractBatchFromRobin(P.batchEmbedLines(odd).join("\n"));
  check(back.batch && JSON.stringify(back.batch) === JSON.stringify(odd), "4 バイト文字が戻らない");
  // 1 文字壊すと検査値で気づく
  const emb = P.batchEmbedLines(odd);
  const k = emb.findIndex((l) => l.indexOf("PADBATCH v1") === 0) + 1;
  emb[k] = (emb[k][0] === "A" ? "B" : "A") + emb[k].slice(1);
  check(!P.extractBatchFromRobin(emb.join("\n")).batch, "壊れた埋め込みを読んでしまった");
  check(/埋め込まれていません/.test(P.extractBatchFromRobin("SET X TO 1").reason), "埋め込み無しの理由が出ない");
}

// ---------------------------------------------------------------- 6. 埋め込みの無い Robin を読み解く
{
  const opt = { detailsPath: "C:\\temp\\d.csv", outDir: "C:\\temp", browser: "edge",
                today: { y: 2026, m: 9, d: 1 } };
  const bare = (b) => P.buildRobin(b, Object.assign({ idCol: (b.options || {}).idCol || "ID" }, opt))
    .robin.split("\n# ---------- 元のバッチ定義")[0];
  for (const f of ["examples/pad/pad_sample_batch.json", "recordings/edi2_practice_batch.json",
                   "recordings/edi2_fetch_batch.json", "tests/fixtures/robin_parse_rich_batch.json"]) {
    const r1 = bare(P.loadRecording(fs.readFileSync(f, "utf8")));
    const got = P.robinToBatch(r1);
    check(got.how === "parse" && got.batch, "読み解けない: " + f);
    if (got.batch) { check(bare(got.batch) === r1, "読み解いたものから同じ Robin にならない: " + f); }
  }
  const none = P.robinToBatch("SET X TO 1");
  check(!none.batch && /ではないようです/.test(none.notes[0]), "Robin でないものの理由が出ない");
}

if (errors.length) {
  console.log("NG  録画の下ごしらえ\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log("OK  録画の下ごしらえ: 押せる要素の優先 / フォーカス外し / Win+Shift+S / 列の自動割り当て / バッチ定義の埋め込み / Robin の読み解き");
