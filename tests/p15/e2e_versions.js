// Импорт ответа в чужую редакцию — обычный браузерный экран (Chromium через Node Playwright).
//
//   node e2e_versions.js a BASE_URL DOC_A OUT_DIR         → upload A, скачать questions.md A и вписать ответ
//   node e2e_versions.js b BASE_URL DOC_B OUT_DIR         → upload B, три попытки импорта (+ экспорт HTML №13)
//
// Фазы разделены, чтобы между ними можно было перезапустить сервер (вчера/сегодня, разные
// mock-сценарии настоящего движка). Итог каждой фазы — JSON в stdout и OUT_DIR/phase-*.json.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [phase, base, docPath, outDir] = process.argv.slice(2);
const log = [];
function check(cond, msg) {
  if (!cond) throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg);
  log.push("ok: " + msg);
}
const api = async (page, p) => (await page.request.get(base + p, { headers: { Accept: "application/json" } })).json();
const calls = async (page) => (await api(page, "/healthz")).engine_calls;
async function waitFinal(page) {
  await page.waitForSelector('body[data-run-status="complete"], body[data-run-status="partial"], body[data-run-status="failed"]', { timeout: 120000 });
}
function runIdOf(url) { return url.split("/runs/")[1].split(/[?#]/)[0]; }
function fillAnswer(md, qid, answer, edit, wording) {
  const re = new RegExp("## " + qid.replace(/[-]/g, "\\-") + "\\n[\\s\\S]*?Ответ:[^\\n]*\\n?");
  const sec = md.match(re)[0];
  const tail = "Ответ: " + answer + "\n" + (edit ? "Правка: «" + edit[0] + "» → «" + edit[1] + "»\n" : "")
    + (wording ? "Формулировка: " + wording + "\n" : "");
  return md.replace(sec, sec.replace(/Ответ:[^\n]*\n?$/, tail));
}
async function upload(page, file) {
  await page.goto(base + "/");
  await page.setInputFiles("#upload-input", file);
  await page.waitForURL(/\/runs\/\d{8}-\d{6}-[0-9a-f]{6}$/);
  await waitFinal(page);
  return runIdOf(page.url());
}
async function downloadQuestions(page, runId, saveAs) {
  await page.goto(base + "/runs/" + runId);
  const [dl] = await Promise.all([page.waitForEvent("download"), page.click("text=Скачать questions.md")]);
  await dl.saveAs(saveAs);
  return fs.readFileSync(saveAs, "utf8");
}
async function firstQuestion(page, runId) {
  await page.goto(base + "/runs/" + runId);
  const q = page.locator("#action .question").first();
  const head = await q.locator("p").first().innerText();
  return { id: head.split(".")[0].trim(), text: head.slice(head.indexOf(".") + 1).replace(/→.*$/, "").trim() };
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1200, height: 900 } });
  const page = await ctx.newPage();
  const shot = (name, p = page) => p.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true });
  const out = { phase };
  try {
    if (phase === "a") {
      out.run_a = await upload(page, docPath);
      out.q_a = await firstQuestion(page, out.run_a);
      await shot("a1-version-A");
      const md = await downloadQuestions(page, out.run_a, path.join(outDir, "questions-A.md"));
      const filled = fillAnswer(md, out.q_a.id, "По дате совершения покупки");
      fs.writeFileSync(path.join(outDir, "answers-A.md"), filled);
      out.answers_a_sha = (filled.match(/source_sha256: ([0-9a-f]{64})/) || [])[1];
      check(!!out.answers_a_sha, "ответ A содержит source_sha256 версии A");
    } else {
      const prev = JSON.parse(fs.readFileSync(path.join(outDir, "phase-a.json"), "utf8"));
      out.run_a = prev.run_a;
      out.run_b = await upload(page, docPath);
      out.q_b = await firstQuestion(page, out.run_b);
      out.sha_b = (await api(page, "/api/runs/" + out.run_b)).input.sha256;
      check(out.q_b.id === prev.q_a.id && out.q_b.text !== prev.q_a.text, `один номер ${out.q_b.id} — разные вопросы в A и B`);

      // 1. Чужой ответ (из A) в просмотр B.
      let c0 = await calls(page);
      await page.goto(base + "/runs/" + out.run_b);
      await page.setInputFiles('input[name="answers_file"]', path.join(outDir, "answers-A.md"));
      await shot("b1-form-with-answer-from-A");
      await Promise.all([page.waitForLoadState("load"), page.click("#confirm")]);
      await page.waitForSelector("#import-rejected");
      await shot("b2-rejected-answer-from-A");
      const rej = await page.locator("#import-rejected").innerText();
      check(rej.includes(prev.q_a.text) && rej.includes(out.q_b.text), "на экране оба вопроса с одним номером");
      check((await page.locator(`a[href="/runs/${out.run_a}#action"]`).count()) === 1, "есть ссылка на вопросы версии A");
      out.foreign = {
        children_b: (await api(page, "/api/runs/" + out.run_b)).children.length,
        engine_calls: (await calls(page)) - c0,
        import: (await api(page, "/api/runs/" + out.run_b)).imports.slice(-1)[0],
      };
      check(out.foreign.children_b === 0 && out.foreign.engine_calls === 0, "чужой ответ: 0 дочерних запусков, 0 вызовов движка");

      // Вторая вкладка с той же формой B — для повторной загрузки правильного ответа.
      const tab2 = await ctx.newPage();
      await tab2.goto(base + "/runs/" + out.run_b);

      // 2. Свой ответ (questions.md B + правка текста).
      const mdB = await downloadQuestions(page, out.run_b, path.join(outDir, "questions-B.md"));
      // Правка в том виде, который применит движок: вопрос №08 с целью — «Формулировка», иначе «было → стало».
      const repB = await (await page.request.get(base + "/runs/" + out.run_b + "/files/report.json?inline=1")).json();
      const qB = repB.questions.find((q) => q.id === out.q_b.id) || {};
      const filledB = qB.target
        ? fillAnswer(mdB, out.q_b.id, "После смены порога разрешён ещё один push", null, "Если результат 400, 401, 403 или 500 — неуспешный.")
        : fillAnswer(mdB, out.q_b.id, "После смены порога разрешён ещё один push",
            ["На карту приходится максимум один такой push за календарный месяц.", "На карту приходится не более одного push за календарный месяц, если порог не менялся."]);
      fs.writeFileSync(path.join(outDir, "answers-B.md"), filledB);
      c0 = await calls(page);
      await page.setInputFiles('input[name="answers_file"]', path.join(outDir, "answers-B.md"));
      await Promise.all([page.waitForURL((u) => !u.toString().endsWith(out.run_b)), page.click("#confirm")]);
      out.child = runIdOf(page.url());
      await waitFinal(page);
      await shot("b3-own-answer-new-revision");
      const childApi = await api(page, "/api/runs/" + out.child);
      out.own = {
        children_b: (await api(page, "/api/runs/" + out.run_b)).children.length,
        engine_calls: (await calls(page)) - c0,
        child_status: childApi.status,
        child_input_sha256: childApi.input.sha256,
        child_document_sha256: childApi.report && childApi.report.document_sha256,
        import: childApi.answers && childApi.answers.import,
      };
      check(out.own.children_b === 1 && out.own.engine_calls === 1, "свой ответ: одна новая редакция, один вызов движка");
      check(out.own.child_document_sha256 && out.own.child_document_sha256 !== out.sha_b, "у новой редакции свой SHA документа");

      // 3. Повтор того же файла из второй вкладки.
      c0 = await calls(tab2);
      await tab2.setInputFiles('input[name="answers_file"]', path.join(outDir, "answers-B.md"));
      await Promise.all([tab2.waitForURL(/dup=1/), tab2.click("#confirm")]);
      await shot("b4-repeat-same-revision", tab2);
      out.repeat = {
        landed_on: runIdOf(tab2.url()),
        children_b: (await api(tab2, "/api/runs/" + out.run_b)).children.length,
        engine_calls: (await calls(tab2)) - c0,
      };
      check(out.repeat.landed_on === out.child && out.repeat.children_b === 1 && out.repeat.engine_calls === 0,
        "повтор: та же редакция, второго запуска нет");

      // 4. Экспорт автономного HTML №13, если отчёт построен №13 (есть выгрузка черновика).
      const html = await page.request.get(base + "/runs/" + out.child + "/files/report.html?inline=1");
      if (html.ok() && (await html.text()).includes('id="ans-export"')) {
        const rep = await ctx.newPage();
        await rep.goto(base + "/runs/" + out.child + "/files/report.html?inline=1");
        const ta = rep.locator("textarea.ans").first();
        const qid13 = await ta.getAttribute("data-qid");
        await ta.fill("Да, после смены порога разрешён ещё один push.\n# строка с решёткой — часть ответа\nПроверено аналитиком.");
        const [dl] = await Promise.all([rep.waitForEvent("download"), rep.click("#ans-export")]);
        const html13 = path.join(outDir, "answers-html13-" + out.child + ".md");
        await dl.saveAs(html13);
        await shot("b5-html13-draft", rep);
        const text = fs.readFileSync(html13, "utf8");
        check(text.includes("format: bcc-review-answers/1") && text.includes("### Ответ"), "экспорт №13: заголовок «### Ответ»");
        c0 = await calls(page);
        await page.goto(base + "/runs/" + out.child);
        await page.setInputFiles('input[name="answers_file"]', html13);
        await Promise.all([page.waitForURL((u) => !u.toString().endsWith(out.child)), page.click("#confirm")]);
        out.html13 = { file: html13, qid: qid13, rev3: runIdOf(page.url()) };
        await waitFinal(page);
        await shot("b6-html13-imported");
        const r3 = await api(page, "/api/runs/" + out.html13.rev3);
        out.html13.import = r3.answers && r3.answers.import;
        out.html13.engine_calls = (await calls(page)) - c0;
        out.html13.status = r3.status;
        check(out.html13.import && out.html13.import.format === "html13", "экспорт №13 принят для своей версии");
      } else {
        out.html13 = "skipped: report.html построен не №13";
      }
    }
    out.log = log;
    fs.writeFileSync(path.join(outDir, "phase-" + phase + ".json"), JSON.stringify(out, null, 1));
    console.log(JSON.stringify(out));
  } catch (err) {
    await shot("zz-failure-" + phase).catch(() => {});
    console.log(JSON.stringify({ error: String((err && err.stack) || err), log, out }));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
