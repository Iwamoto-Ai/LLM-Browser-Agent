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
// 明細ファイル名はフローごとに入れる欄（空だと変換できない）。ここでは空のときだけ入れて試す。
// 名前そのものを確かめる箇所は、自分で値を入れてから押す
d.addEventListener("click", (e) => {
  if (e.target && e.target.id === "run") {
    const n = d.getElementById("detailsName");
    if (n && !n.value && !d.getElementById("detailsFromResult").checked) { n.value = "edi2_batch.csv"; }
  }
}, true);
for (const id of ["run", "copy", "save", "copyJs", "saveTemplate", "batchFile", "drop", "ver",
                  "idcol", "idcolHint", "detailsFile"]) {
  if (!d.getElementById(id)) { errors.push("要素が無い: #" + id); }
}
// 3. オプションの欄（ドライバーはフォルダで受け取る。exe のパス欄は残さない）
for (const id of ["driverDir", "proxyAuto", "autodrv", "showDrvInfo", "maxItems", "winW", "winH",
                  "detailsName", "downloadFolder", "idcol", "outdir",
                  "stepWait", "preferClickable", "blurAfterFill", "shotFromKeys", "autoColumns"]) {
  if (!d.getElementById(id)) { errors.push("要素が無い: #" + id); }
}
{
  const W = dom.window.PadConvert;
  const ws = W.windowSize([], "abc", "0");
  if (ws.w !== 1250 || ws.h !== 900) { errors.push("ウィンドウの既定が 1250×900 でない: " + JSON.stringify(ws)); }
  const wr = W.windowSize([{ type: "setViewport", width: 1366, height: 1134 }]);
  if (wr.w !== 1366 || wr.h !== 1134) { errors.push("録画の setViewport を使っていない"); }
  if (W.driverDirOf("", "C:\\temp\\msedgedriver.exe") !== "C:\\temp") {
    errors.push("exe のパスからフォルダを取り出せていない");
  }
}
if (d.getElementById("driver")) { errors.push("ドライバーの exe パス欄が残っている: #driver"); }
for (const id of ["proxyAuto", "autodrv", "showDrvInfo", "preferClickable", "blurAfterFill",
                  "shotFromKeys", "autoColumns"]) {
  if (d.getElementById(id) && !d.getElementById(id).checked) {
    errors.push("既定でオンになっていない: #" + id);
  }
}
if (d.getElementById("maxItems") && d.getElementById("maxItems").value !== "1") {
  errors.push("MaxItems の既定が 1 でない");
}
// 自動取得オンのあいだはドライバーの置き場所を使わないので、灰色にする
{
  const ad = d.getElementById("autodrv"), dd = d.getElementById("driverDir");
  if (ad && dd) {
    if (!dd.disabled) { errors.push("自動取得オンなのに置き場所の欄が使える"); }
    ad.checked = false;
    ad.dispatchEvent(new dom.window.Event("change"));
    if (dd.disabled) { errors.push("自動取得をオフにしても置き場所の欄が灰色のまま"); }
    ad.checked = true;
    ad.dispatchEvent(new dom.window.Event("change"));
  }
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
// 起点までのメニュー移動（クリック）は setup に残す。フローが辿るため
const menu = steps.findIndex((s, i) => i > 3 && s.type === "click" && as[i].sec === "setup");
if (steps.some((s, i) => s.type === "click" && as[i].sec === "skip" && i < 4)) {
  // ログインボタンは skip でも構わない
}
if (as.filter((x) => x.sec === "setup").length < 1) {
  errors.push("setup が空になっている");
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

// バッチ定義 → 振り分け → バッチ定義 が元に戻るか（読み込んで直せること）
const sample = JSON.parse(fs.readFileSync("recordings/edi2_delivery_batch.json", "utf8")
  .split("\n").filter((l) => !l.trim().startsWith("//")).join("\n"));
const back = P.batchToSteps(sample);
const rebuilt = P.buildBatch(back.steps, back.assigns, sample.title);
const norm = (arr) => JSON.stringify((arr || []).map((s) =>
  JSON.stringify(Object.keys(s).sort().reduce((o, k) => (o[k] = s[k], o), {}))));
// 結果 CSV を明細にするとき skip 列を見ないこと。
// 結果 CSV に skip 列は無いので、判定を出すと「列が見つかりません」で止まる。
// Python 版と食い違いやすい箇所なので、ブラウザ版でも確かめる。
const optOn = { detailsPath: "C:\\t\\d.csv", idCol: "ID", driverExe: "C:\\t\\e.exe",
                outDir: "C:\\t", proxy: "", autoDriver: false, browser: "edge",
                detailsFromResult: true };
const robinOn = P.buildRobin(P.loadRecording(
  fs.readFileSync("recordings/edi2_fetch_batch.json", "utf8")), optOn).robin;
if (robinOn.indexOf("Row['skip']") >= 0) {
  errors.push("結果 CSV を明細にするのに skip 列を見ている");
}
if (robinOn.indexOf("pad_result_2.csv") < 0) {
  errors.push("結果 CSV を明細にするのに出力先が切り替わっていない");
}

// 画面の入力欄と、設定を書き戻す先の id がそろっていること。
// idCol / idcol のように大文字小文字を取り違えると、読み込んでも入らない。
const uiHtml = fs.readFileSync("tools/pad_converter.html", "utf8");
["idcol", "browser", "shotName", "detailsFromResult",
 "driverDir", "proxyAuto", "maxItems", "winW", "winH"].forEach((id) => {
  if (uiHtml.indexOf('id="' + id + '"') < 0) {
    errors.push("入力欄が見つからない: " + id);
  }
  if (uiHtml.indexOf('$("' + id + '")') < 0) {
    errors.push("設定を書き戻していない: " + id);
  }
});

// バッチ定義に持たせた設定が往復で保たれること。
// 読み込んだときに画面へ戻す仕組みなので、消えると毎回入力し直しになる。
const withOpt = P.buildBatch(back.steps, back.assigns, sample.title,
  { idCol: "プロジェクト番号", browser: "chrome", shotName: "@ID@",
    detailsFromResult: true });
const readBack = P.batchOptions(withOpt);
if (readBack.idCol !== "プロジェクト番号" || readBack.browser !== "chrome" ||
    readBack.shotName !== "@ID@" || readBack.detailsFromResult !== true) {
  errors.push("バッチ定義の設定が往復で変わる: " + JSON.stringify(readBack));
}
// PC ごとに違うものは入らないこと（配ったときに人のフォルダが混ざらないように）
const j2 = JSON.stringify(withOpt);
["outDir", "driverExe", "detailsPath", "proxy", "downloadDir"].forEach((k) => {
  if (j2.indexOf(k) >= 0) { errors.push("PC 固有の設定が入っている: " + k); }
});

// capture の列名が往復で消えないこと（消えると結果 CSV の見出しが
// 「取得値」になり、次のバッチが列を引けなくなる）
const capsIn = (sample.loop || []).filter((s) => s.type === "capture").map((s) => s.name);
const capsOut = (rebuilt.loop || []).filter((s) => s.type === "capture").map((s) => s.name);
if (JSON.stringify(capsIn) !== JSON.stringify(capsOut)) {
  errors.push("capture の列名が変わる: " + capsIn + " → " + capsOut);
}
for (const key of ["setup", "loop", "recover"]) {
  if (norm(sample[key]) !== norm(rebuilt[key])) {
    errors.push("バッチ定義の復元で " + key + " が変わる");
  }
}

// 埋め込みの無い古い Robin を読み込むと、読み解いて組み立て、戻せなかった点を出す
{
  const txt = fs.readFileSync("tests/fixtures/old_edi2_publish_robin.txt", "utf8");
  const file = new dom.window.File([txt], "old.robin.txt", { type: "text/plain" });
  const input = d.getElementById("batchFile");
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new dom.window.Event("change"));
  await new Promise((r) => setTimeout(r, 300));
  const msg = d.getElementById("msg").textContent;
  if (msg.indexOf("Robin を読み解いてバッチ定義を組み立てました") < 0) {
    errors.push("古い Robin を読み解けていない: " + msg.slice(0, 120));
  }
  if (msg.indexOf("運用の設定") < 0) { errors.push("戻せなかった点が出ていない"); }
  if (d.getElementById("saveBatch").disabled) { errors.push("読み解いたバッチ定義を保存できない"); }
}

// PAD で手直しした Robin を読み込むと、違いを並べ、手直しの前・後を切り替えられる
{
  const P = dom.window.PadConvert;
  const b = P.loadRecording(fs.readFileSync("recordings/edi2_accept_batch.json", "utf8"));
  const r = P.buildRobin(b, { detailsPath: "C:\\temp\\d.csv", idCol: "プロジェクト番号", outDir: "C:\\temp",
                              browser: "edge", today: { y: 2026, m: 9, d: 1 } }).robin;
  // 置き換えは split / join で（replace の置き換え文字列では $' が特別な意味になる）
  const edited = r.split("file:///C:/temp/index.html").join("file:///C:/x/index.html");
  const input = d.getElementById("batchFile");
  Object.defineProperty(input, "files", { value: [new dom.window.File([edited], "edited.robin.txt")], configurable: true });
  input.dispatchEvent(new dom.window.Event("change"));
  await new Promise((res) => setTimeout(res, 300));
  let msg = d.getElementById("msg").textContent;
  if (msg.indexOf("いま使っているもの：手直しの後") < 0 || msg.indexOf("file:///C:/x/index.html") < 0) {
    errors.push("手直しした Robin の違いが出ていない: " + msg.slice(0, 400));
  }
  const btn = d.getElementById("useEmbedded");
  if (!btn) { errors.push("埋め込み（手直しの前）に切り替えるボタンが無い"); }
  else {
    btn.click();
    await new Promise((res) => setTimeout(res, 100));
    msg = d.getElementById("msg").textContent;
    if (msg.indexOf("いま使っているもの：手直しの前") < 0 || !d.getElementById("useEdited")) {
      errors.push("埋め込み（手直しの前）に切り替わらない: " + msg.slice(0, 160));
    }
  }
}

// 開くページ（TargetUrl）: 録画の URL が欄に入り、直すとバッチ定義と Robin に入る
{
  d.getElementById("resetAll").click();
  const rec = fs.readFileSync("tests/fixtures/oracle_asn_recording.json", "utf8");
  const input = d.getElementById("batchFile");
  Object.defineProperty(input, "files", { value: [new dom.window.File([rec], "rec.json")], configurable: true });
  input.dispatchEvent(new dom.window.Event("change"));
  await new Promise((res) => setTimeout(res, 300));
  const f = d.getElementById("targetUrl");
  if (f.value !== "https://edi.example.com/OA_HTML/OA.jsp?OAFunc=OANEWHOMEPAGE") {
    errors.push("録画の URL が開くページの欄に入っていない: " + f.value);
  }
  // ログイン後の URL らしい値には注意が出る
  f.value = "https://edi.example.com/OA_HTML/OA.jsp?_ti=1&oas=x";
  f.dispatchEvent(new dom.window.Event("input"));
  if (d.getElementById("targetUrlWarn").hidden) { errors.push("ログイン後の URL に注意が出ない"); }
  f.value = "https://edi.example.com/OA_HTML/AppsLocalLogin.jsp";
  f.dispatchEvent(new dom.window.Event("input"));
  if (!d.getElementById("targetUrlWarn").hidden) { errors.push("入り口の URL なのに注意が出る"); }
  // バッチ定義を読み込んだときも、その URL が欄に入る。直して変換すると Robin と埋め込みに入る
  const bj = fs.readFileSync("recordings/edi2_accept_batch.json", "utf8");
  Object.defineProperty(input, "files", { value: [new dom.window.File([bj], "accept.json")], configurable: true });
  input.dispatchEvent(new dom.window.Event("change"));
  await new Promise((res) => setTimeout(res, 300));
  if (f.value !== "file:///C:/temp/index.html") { errors.push("バッチ定義の URL が欄に入っていない: " + f.value); }
  f.value = "https://edi.example.com/OA_HTML/AppsLocalLogin.jsp";
  f.dispatchEvent(new dom.window.Event("input"));
  d.getElementById("idcol").value = "プロジェクト番号";
  d.getElementById("run").click();
  await new Promise((res) => setTimeout(res, 100));
  const out = d.getElementById("out").value;
  if (out.indexOf("SET TargetUrl TO $'''https://edi.example.com/OA_HTML/AppsLocalLogin.jsp'''") < 0) {
    errors.push("直した開くページが Robin に入っていない: " + d.getElementById("msg").textContent.slice(0, 200) + " / " + d.getElementById("assignMsg").textContent.slice(0, 200));
  }
  const back = dom.window.PadConvert.extractBatchFromRobin(out).batch;
  if (!back || dom.window.PadConvert.getTargetUrl(back) !== "https://edi.example.com/OA_HTML/AppsLocalLogin.jsp") {
    errors.push("直した開くページが埋め込みのバッチ定義に入っていない");
  }
  d.getElementById("resetAll").click();
  if (f.value !== "") { errors.push("最初からやり直しで開くページの欄が空にならない"); }
}

// 保存したファイルを確かめる: 振り分けの表で設定すると、バッチ定義と Robin に入り、読み直しても残る
{
  d.getElementById("resetAll").click();
  const input = d.getElementById("batchFile");
  const bj = fs.readFileSync("recordings/edi2_fetch_batch.json", "utf8");
  Object.defineProperty(input, "files", { value: [new dom.window.File([bj], "fetch.json")], configurable: true });
  input.dispatchEvent(new dom.window.Event("change"));
  await new Promise((res) => setTimeout(res, 300));
  const t = d.getElementById("assignTable");
  const dl = [...t.querySelectorAll(".dlChk")].find((el) => el.checked);
  if (!dl) {
    errors.push("ダウンロードの行が振り分けの表に無い");
  } else {
    const i = dl.dataset.i;
    const box = t.querySelector('.dlCheck[data-i="' + i + '"]');
    if (!box || box.hidden) { errors.push("ダウンロードの行に「保存したファイルを確かめる」が出ない"); }
    const chk = t.querySelector('.dlChkChk[data-i="' + i + '"]');
    chk.checked = true; chk.dispatchEvent(new dom.window.Event("change"));
    if (t.querySelector('.dlChkBox[data-i="' + i + '"]').hidden) { errors.push("確かめる欄が開かない"); }
    const cells = t.querySelector('.dlChkCells[data-i="' + i + '"]');
    cells.value = "l11"; cells.dispatchEvent(new dom.window.Event("input"));
    const rule = t.querySelector('.dlChkRule[data-i="' + i + '"]');
    const val = t.querySelector('.dlChkValue[data-i="' + i + '"]');
    if (!val.hidden) { errors.push("「値がある」なのに値の欄が出ている"); }
    rule.value = "equals"; rule.dispatchEvent(new dom.window.Event("change"));
    if (val.hidden) { errors.push("「次と同じ」で値の欄が出ない"); }
    val.value = "16,600"; val.dispatchEvent(new dom.window.Event("input"));
    d.getElementById("makeBatch").click();
    d.getElementById("run").click();
    await new Promise((res) => setTimeout(res, 100));
    const out = d.getElementById("out").value;
    const want = 'SET DlCheck TO $\'\'\'{"cells": "L11", "rule": "equals", "sheet": "", "value": "16,600"}\'\'\'';
    if (out.indexOf(want) < 0) { errors.push("確かめる設定が Robin に入っていない: " + d.getElementById("msg").textContent.slice(0, 200)); }
    if (out.indexOf("NewName: $'''%DlName%_NG'''") < 0) { errors.push("外れたときの _NG が Robin に無い"); }
    const back = dom.window.PadConvert.extractBatchFromRobin(out).batch;
    const bdl = back && back.loop.find((st) => st.type === "download");
    if (!bdl || !bdl.checkFile || bdl.checkFile.value !== "16,600") { errors.push("確かめる設定が埋め込みのバッチ定義に入っていない"); }
    // そのバッチ定義を読み直すと、表に設定が戻る
    Object.defineProperty(input, "files", { value: [new dom.window.File([JSON.stringify(back)], "back.json")], configurable: true });
    input.dispatchEvent(new dom.window.Event("change"));
    await new Promise((res) => setTimeout(res, 300));
    const c2 = [...t.querySelectorAll(".dlChkChk")].find((el) => el.checked);
    if (!c2 || t.querySelector('.dlChkCells[data-i="' + c2.dataset.i + '"]').value !== "L11" ||
        t.querySelector('.dlChkRule[data-i="' + c2.dataset.i + '"]').value !== "equals") {
      errors.push("読み直したバッチ定義の確かめる設定が表に戻らない");
    }
  }
  d.getElementById("resetAll").click();
}

// フローの設定: 明細ファイル名・ダウンロードのフォルダ名・ID 列はバッチ定義に入り、読み込むと切り替わる
{
  const load = async (obj, name) => {
    const input = d.getElementById("batchFile");
    Object.defineProperty(input, "files", { value: [new dom.window.File([JSON.stringify(obj)], name)], configurable: true });
    input.dispatchEvent(new dom.window.Event("change"));
    await new Promise((res) => setTimeout(res, 300));
  };
  d.getElementById("resetAll").click();
  d.getElementById("outdir").value = "C:\\temp";
  const base = dom.window.PadConvert.loadRecording(fs.readFileSync("recordings/edi2_practice_batch.json", "utf8"));
  const a = JSON.parse(JSON.stringify(base));
  a.options = Object.assign({}, a.options || {}, { idCol: "プロジェクト番号", detailsName: "明細_EDI_A.xlsx",
                                                   downloadFolder: "download_EDI_A", winW: 1111, winH: 777 });
  await load(a, "a.json");
  const nm = d.getElementById("detailsName"), df = d.getElementById("downloadFolder");
  if (nm.value !== "明細_EDI_A.xlsx" || df.value !== "download_EDI_A") {
    errors.push("バッチ定義の明細ファイル名・ダウンロードのフォルダ名が欄に戻らない: " + nm.value + " / " + df.value);
  }
  if (d.getElementById("winW").value !== "1111") { errors.push("バッチ定義のウィンドウサイズが欄に戻らない"); }
  d.getElementById("run").click();
  await new Promise((res) => setTimeout(res, 100));
  let out = d.getElementById("out").value;
  if (out.indexOf("SET DetailsFile TO $'''%BaseDir%\\\\明細_EDI_A.xlsx'''") < 0) {
    errors.push("明細ファイル名が BaseDir とつながって Robin に入らない");
  }
  if (out.indexOf("SET DlDir TO $'''C:\\\\temp\\\\download_EDI_A'''") < 0) {
    errors.push("ダウンロードのフォルダ名が Robin に入らない");
  }
  // 読み込んだあとに欄を直して変換すると、埋め込みのバッチ定義にも入る
  nm.value = "明細_EDI_A2.xlsx";
  d.getElementById("run").click();
  await new Promise((res) => setTimeout(res, 100));
  out = d.getElementById("out").value;
  let back = dom.window.PadConvert.extractBatchFromRobin(out).batch;
  if (!back || back.options.detailsName !== "明細_EDI_A2.xlsx" || back.options.downloadFolder !== "download_EDI_A") {
    errors.push("直した明細ファイル名が埋め込みに入らない: " + JSON.stringify(back && back.options));
  }
  // 名前の入っていない古いバッチ定義を読み込むと、前のフローの名前を引き継がず、注意を出す
  const old = JSON.parse(JSON.stringify(base));
  if (old.options) { delete old.options.detailsName; }
  await load(old, "old.json");
  if (nm.value === "明細_EDI_A2.xlsx") { errors.push("前に読み込んだフローの明細ファイル名が残っている"); }
  if (d.getElementById("detailsNameWarn").hidden) { errors.push("明細ファイル名の無いバッチ定義に注意が出ない"); }
  // BaseDir の外のフルパスは使わない。BaseDir の下のフルパスは名前に直す
  nm.value = "D:\\work\\明細.xlsx";
  d.getElementById("run").click();
  await new Promise((res) => setTimeout(res, 100));
  if (!d.getElementById("msg").querySelector(".err") || d.getElementById("detailsNameWarn").hidden) {
    errors.push("BaseDir の外のフルパスで変換できてしまう");
  }
  nm.value = "C:\\temp\\明細\\明細_EDI_B.csv";
  d.getElementById("run").click();
  await new Promise((res) => setTimeout(res, 100));
  if (nm.value !== "明細\\明細_EDI_B.csv") { errors.push("BaseDir の下のフルパスが名前に直らない: " + nm.value); }
  // この PC のブラウザーには、明細・ダウンロードの名前を覚えない
  let saved = {};
  try { saved = JSON.parse(dom.window.localStorage.getItem("pad_converter_paths") || "{}"); } catch (e) { saved = {}; }
  if ("details" in saved || "downloadDir" in saved || "detailsName" in saved) {
    errors.push("明細・ダウンロードの名前を PC 側に覚えている: " + Object.keys(saved).join(","));
  }
  d.getElementById("resetAll").click();
  if (nm.value !== "" || df.value !== "") { errors.push("最初からやり直しで明細ファイル名が空にならない"); }
}

// 明細ファイルを選ぶと、明細ファイル名と ID 列が入る（BaseDir の下のフォルダは残す）
{
  const pick = async (text, name) => {
    const input = d.getElementById("detailsFile");
    Object.defineProperty(input, "files", { value: [new dom.window.File([text], name)], configurable: true });
    input.dispatchEvent(new dom.window.Event("change"));
    await new Promise((res) => setTimeout(res, 200));
  };
  d.getElementById("resetAll").click();
  const nm = d.getElementById("detailsName"), idc = d.getElementById("idcol");
  idc.value = "要求ID";                                  // 前のフローの ID 列が残っている
  await pick("プロジェクト番号,発注番号,skip\nPM1,1001,\n", "明細_EDI_A.csv");
  if (nm.value !== "明細_EDI_A.csv") { errors.push("選んだ明細の名前が明細ファイル名に入らない: " + nm.value); }
  if (idc.value !== "プロジェクト番号") { errors.push("選んだ明細に無い ID 列が先頭列に変わらない: " + idc.value); }
  idc.value = "発注番号";                                 // 明細にある列なら、そのまま
  nm.value = "明細\\古い.csv";
  await pick("プロジェクト番号,発注番号,skip\nPM1,1001,\n", "明細_EDI_B.csv");
  if (nm.value !== "明細\\明細_EDI_B.csv") { errors.push("明細ファイル名の BaseDir の下のフォルダが残らない: " + nm.value); }
  if (idc.value !== "発注番号") { errors.push("明細にある ID 列まで先頭列に変わった: " + idc.value); }
  d.getElementById("resetAll").click();
}

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
