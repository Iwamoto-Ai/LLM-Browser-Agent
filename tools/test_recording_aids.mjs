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
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import zlib from "node:zlib";

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
  // リンク先を保存: 押さずに、包んでいるリンクの先を fetch で受け取り、pad_download.拡張子 で保存する
  // （実機の Oracle EBS では、リンクの写しを押すと認証エラー、fetch なら Excel が取れた）
  const body = '<a id="res" href="OA.jsp?_rc=FNDCPREQUESTVIEWPAGE&amp;OUTPUT=Y"><img id="icon" src="r.gif"></a>';
  const make = (resp) => {
    const dom = new JSDOM("<!doctype html><body>" + body + "</body>",
                          { runScripts: "outside-only", url: "https://edi.example.com/OA_HTML/x.jsp" });
    const w = dom.window, st = { fetched: [], saved: [] };
    w.fetch = (url, opt) => { st.fetched.push({ url, cred: opt && opt.credentials }); return Promise.resolve(resp); };
    w.URL.createObjectURL = () => "blob:x";
    w.URL.revokeObjectURL = () => {};
    w.document.addEventListener("click", (e) => {
      st.saved.push({ id: e.target.id, dl: e.target.download, href: e.target.href });
      e.preventDefault();
    }, true);
    const fn = w.eval("(function () { return function () { " + P.jsActOneline(true, true) + " }; })()");
    return { w, st, fn };
  };
  const reply = (type, disp, text, size) => ({
    headers: { get: (k) => (k === "content-type" ? type : k === "content-disposition" ? disp : null) },
    blob: () => Promise.resolve({ size: size, text: () => Promise.resolve(text) })
  });
  const tick = () => new Promise((r) => setTimeout(r, 20));
  // Excel（日本語の名前は Shift-JIS のまま来て文字化けしても、拡張子は取れる）
  let m = make(reply("application/vnd.ms-excel", "inline; filename =\"XXPO_\u00fb\u00f3_191126.xls\"", "", 43008));
  let res = m.fn(["#icon"], "saveLink", "");
  await tick();
  check(res.ok, "リンク先を保存が失敗した");
  check(m.st.fetched.length === 1 && m.st.fetched[0].cred === "include" &&
        m.st.fetched[0].url === "https://edi.example.com/OA_HTML/OA.jsp?_rc=FNDCPREQUESTVIEWPAGE&OUTPUT=Y",
        "リンク先をログイン状態で 1 回だけ取りに行っていない: " + JSON.stringify(m.st.fetched));
  check(m.st.saved.length === 1 && m.st.saved[0].dl === "pad_download.xls",
        "受け取った中身を pad_download.xls で保存していない: " + JSON.stringify(m.st.saved));
  check(!m.w.document.querySelector("a[download]"), "保存用のリンクが残っている");
  // 名前が無ければ種類から
  m = make(reply("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", null, "", 9000));
  m.fn(["#icon"], "saveLink", "");
  await tick();
  check(m.st.saved.length === 1 && m.st.saved[0].dl === "pad_download.xlsx", "種類から拡張子を決めていない");
  // 認証エラーの文字だけなら保存しない（ダウンロードが来ないので、その件は失敗になる）
  m = make(reply("text/plain", null, "Authentication failed.\n", 23));
  m.fn(["#icon"], "saveLink", "");
  await tick();
  check(m.st.saved.length === 0 && m.w.__padDlError === "Authentication failed.",
        "認証エラーの文字を保存してしまった: " + JSON.stringify(m.st.saved));
  // リンクが無ければ失敗
  check(!make(reply("", null, "", 0)).fn(["#nolink"], "saveLink", "").ok, "リンクが無いのに成功した");
}
{
  // ウィンドウが前面で操作中でないと、focus() / blur() を呼んでも合図が出ない。
  // 実 EDI1 の年月の欄は、外れた合図で 202610 を 2026-10 に整える。合図が出なかったときは
  // こちらから出して、整える仕掛けを動かす（出たときは二重に出さない）
  const field = '<input name="yyyymm" maxlength="7" onfocus="this.dataset.f=(+(this.dataset.f||0)+1)" ' +
    'onblur="this.dataset.b=(+(this.dataset.b||0)+1);if(this.value.length===6){this.value=this.value.slice(0,4)+String.fromCharCode(45)+this.value.slice(4)}">';
  const run = (silent) => {
    const dom = new JSDOM("<!doctype html><body>" + field + "</body>", { runScripts: "dangerously" });
    const w = dom.window;
    if (silent) {   // 合図が出ない状態をまねる
      w.HTMLElement.prototype.focus = function () {};
      w.HTMLElement.prototype.blur = function () {};
    }
    const fn = w.eval("(function () { return function () { " + P.jsActOneline(true, true) + " }; })()");
    const res = fn(["[name=yyyymm]"], "fill", "202610");
    const el = w.document.querySelector("[name=yyyymm]");
    return { res, v: el.value, f: el.dataset.f, b: el.dataset.b };
  };
  const quiet = run(true);
  check(quiet.res.ok && quiet.v === "2026-10", "合図が出ないとき、年月が整わない: " + quiet.v);
  check(quiet.f === "1" && quiet.b === "1", "合図が出ないとき、こちらから 1 回ずつ出していない: " + JSON.stringify(quiet));
  const normal = run(false);
  check(normal.v === "2026-10" && normal.f === "1" && normal.b === "1",
        "合図が出るときに二重に出している: " + JSON.stringify(normal));
}
{
  // 画面が落ち着くまで待つ（idle）: 少しあとに動く予約（setTimeout）・押した直後を「忙しい」と見る。
  // 実 EDI1 の年月の欄は、値が変わると 1 秒後に自動で送信する（その間に検索を押すと消される）
  const page = '<input name="ym" onchange="setTimeout(String.fromCharCode(119,105,110,100,111,119,46,115,101,110,116,61,49),300)">' +
               '<button id="go">検索</button>';
  const dom = new JSDOM("<!doctype html><body>" + page + "</body>", { runScripts: "dangerously" });
  const w = dom.window;
  const fn = w.eval("(function () { return function () { " + P.jsActOneline(true, true) + " }; })()");
  // 読み込み中は「忙しい」と見る（正しい）。読み終わってから試す
  check(w.document.readyState === "complete" || !fn([], "idle", "").ok, "読み込み中を忙しいと見ていない");
  while (w.document.readyState !== "complete") { await new Promise((r) => setTimeout(r, 10)); }
  const first = fn([], "idle", "");
  check(first.ok, "何もしていないのに忙しいと言う: " + first.text);
  fn(["[name=ym]"], "fill", "202610");
  const busy = fn([], "idle", "");
  check(!busy.ok && /予約1/.test(busy.text), "自動送信の予約を数えていない: " + JSON.stringify(busy));
  await new Promise((r) => setTimeout(r, 400));
  check(w.sent === 1, "予約していた処理が動いていない（仕掛けが文字の setTimeout を壊した）");
  const calm = fn([], "idle", "");
  check(calm.ok, "予約が動いたあとも忙しいと言う: " + calm.text);
  fn(["#go"], "click", "");
  const justClicked = fn([], "idle", "");
  check(!justClicked.ok && /押した直後/.test(justClicked.text), "押した直後を忙しいと見ていない: " + justClicked.text);
  await new Promise((r) => setTimeout(r, 750));
  check(fn([], "idle", "").ok, "押してしばらくたっても忙しいと言う");
}
{
  // フレーム型の画面: 位置で決めた目印（form > input:nth-of-type(1)）が、先に見た別のフレームの
  // 隠れた入力欄に当たっていた（実 EDI1 の「検索」）。見えない要素は押さず、録画のフレームがあれば
  // そのフレームの中だけで探す
  const dom = new JSDOM('<!doctype html><body><iframe name="fr_dmy"></iframe><iframe name="fr_main"></iframe></body>',
                        { runScripts: "outside-only" });
  const w = dom.window;
  const put = (name, html) => { const d = w.frames[name] ? w.frames[name].document : null;
                                d.open(); d.write("<!doctype html><body>" + html + "</body>"); d.close(); return d; };
  const dmy = put("fr_dmy", '<form><input type="hidden" name="pageno" value="1462"></form>');
  const main = put("fr_main", '<form><input type="submit" name="btn_submit" value="検  索"></form>');
  let hit = [];
  dmy.querySelector("input").addEventListener("click", () => hit.push("dmy"));
  main.querySelector("input").addEventListener("click", (e) => { hit.push("main"); e.preventDefault(); });
  const fn = w.eval("(function () { return function () { " + P.jsActOneline(true, true) + " }; })()");
  const sel = ["form > input:nth-of-type(1)"];
  let r = fn(sel, "click", "");
  check(r.ok && hit.join() === "main", "隠れた入力欄を押した（フレームの記録なし）: " + hit.join());
  hit = [];
  r = fn(sel, "click", "", [1]);
  check(r.ok && hit.join() === "main", "録画のフレーム [1] の中で探していない: " + hit.join());
  hit = [];
  r = fn(sel, "click", "", "fr_main");
  check(r.ok && hit.join() === "main", "フレームの名前で探していない: " + hit.join());
  hit = [];
  r = fn(sel, "click", "", [0]);
  check(!r.ok && hit.length === 0, "見えない要素しか無いのに押せたことになった: " + JSON.stringify(r));
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

// ---------------------------------------------------------------- 7. 明細を Excel で受け取る
{
  const inflate = (u8) => new Uint8Array(zlib.inflateRawSync(u8));
  // Excel（ここでは openpyxl）で作った明細。「明細」シートを選び、番号・日付・先頭 0 を崩さない
  const x = await P.readXlsxDetails(new Uint8Array(fs.readFileSync("tests/fixtures/details_sample.xlsx")), inflate);
  check(x.sheet === "明細" && x.sheetFound, "「明細」シートを選んでいない: " + x.sheet);
  check(JSON.stringify(x.headers) === JSON.stringify(["プロジェクト番号", "発注番号", "納入日", "コード", "skip"]),
        "Excel の列名が違う: " + JSON.stringify(x.headers));
  check(JSON.stringify(x.firstRow) === JSON.stringify(["PM9000000001", "900000000001", "2026/09/01", "0012", ""]),
        "Excel の 1 件目が違う: " + JSON.stringify(x.firstRow));
  // 練習用の明細は CSV と Excel の 2 つ。中身がずれていないこと
  const pc = fs.readFileSync("data/edi2_practice_batch.csv", "utf8").replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const px = await P.readXlsxDetails(new Uint8Array(fs.readFileSync("data/edi2_practice_batch.xlsx")), inflate);
  check(px.sheetFound && JSON.stringify(px.headers) === JSON.stringify(pc[0].split(",")),
        "練習用の明細（Excel）の列名が CSV と違う");
  check(JSON.stringify(px.firstRow) === JSON.stringify(pc[1].split(",").concat([""]).slice(0, px.headers.length)),
        "練習用の明細（Excel）の 1 件目が CSV と違う: " + JSON.stringify(px.firstRow));
  // テンプレートは「明細」シート・列名だけ。読み直すと同じ列名
  const cols = P.detailsTemplateColumns(["番号", "発注 & <名>"], false);
  check(cols[cols.length - 1] === "skip", "テンプレートに skip 列が無い");
  check(P.detailsTemplateColumns(["番号"], true).indexOf("skip") < 0, "前の結果を読むバッチに skip 列を足した");
  const t = await P.readXlsxDetails(P.xlsxTemplate(cols), inflate);
  check(t.sheetFound && JSON.stringify(t.headers) === JSON.stringify(cols), "テンプレートを読み直せない");
  fs.writeFileSync(path.join(os.tmpdir(), "pad_template_check.xlsx"), P.xlsxTemplate(cols));
  // Excel の明細なら Robin に Excel の読み込みが入り、CSV なら入らない
  const b = P.loadRecording(fs.readFileSync("tests/fixtures/robin_parse_rich_batch.json", "utf8"));
  const o = { idCol: "番号", outDir: "C:\\temp", browser: "edge", today: { y: 2026, m: 9, d: 1 } };
  const rx = P.buildRobin(b, Object.assign({ detailsPath: "C:\\temp\\d.xlsx" }, o));
  const rc = P.buildRobin(b, Object.assign({ detailsPath: "C:\\temp\\d.csv" }, o));
  check(rx.robin.indexOf("Excel.ReadFromExcel.ReadAllCells") >= 0, "xlsx なのに Excel で読んでいない");
  check(rc.robin.indexOf("Excel.") < 0, "CSV なのに Excel のアクションが入った");
  check(rx.warns.length === rc.warns.length, "Excel の部分で警告が出る: " + rx.warns.join(" / "));
  check(JSON.stringify(rx.columns) === JSON.stringify(["番号", "発注"]), "変換結果の列が違う: " + JSON.stringify(rx.columns));
}

if (errors.length) {
  console.log("NG  録画の下ごしらえ\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log("OK  録画の下ごしらえ: 押せる要素の優先 / フォーカス外し / Win+Shift+S / 列の自動割り当て / バッチ定義の埋め込み / Robin の読み解き / Excel の明細 / リンク先を保存 / 合図の出ない入力欄 / 画面が落ち着くまで待つ / フレームと見えない要素");
