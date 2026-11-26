// Путь банковского аналитика на штатно запущенном веб-приложении (Chromium через Node Playwright).
//
//   node e2e_demo.js BASE_URL DOC OUT_DIR
//
// Загрузка → прогресс (обновление страницы посреди прогона) → замечание с цитатой → ответ владельца
// с новой формулировкой → изменённый пункт после повторной проверки → скачивание результата →
// прежняя ссылка на первую версию. На каждом шаге сверяется, что статус, вопрос и файлы
// относятся к одной версии документа. Кадры: OUT_DIR/frame-*.png, видео: OUT_DIR/video/*.webm,
// итог: OUT_DIR/demo.json.
const { chromium } = require("playwright");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const [base, doc, out] = process.argv.slice(2);
const log = [];
const res = { frames: [], checks: [] };
function check(cond, msg) {
  if (!cond) throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg);
  log.push("ok: " + msg);
}
const sha = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const runIdOf = (url) => url.split("/runs/")[1].split(/[?#]/)[0];
const FINAL = 'body[data-run-status="complete"], body[data-run-status="partial"], body[data-run-status="failed"]';

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    acceptDownloads: true, viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2,
    recordVideo: { dir: path.join(out, "video"), size: { width: 1280, height: 800 } },
  });
  const page = await ctx.newPage();
  const api = async (p) => (await page.request.get(base + p, { headers: { Accept: "application/json" } })).json();
  const text = async (p) => (await page.request.get(base + p)).text();
  const frame = async (name, caption, target) => {
    const file = path.join(out, `frame-${name}.png`);
    if (target) await target.screenshot({ path: file });
    else await page.screenshot({ path: file });
    res.frames.push({ file, caption, url: page.url() });
  };

  // Одна версия: статус страницы = статус API, версия вопросов = document.id отчёта = source_sha256 questions.md.
  async function sameVersion(runId, label) {
    const st = await api("/api/runs/" + runId);
    const rep = JSON.parse(await text(`/runs/${runId}/files/report.json?inline=1`));
    const qmd = await text(`/runs/${runId}/questions.md`);
    const qsha = (qmd.match(/source_sha256: ([0-9a-f]{64})/) || [])[1];
    const pageStatus = await page.getAttribute("body", "data-run-status");
    const versionOnPage = await page.locator("#version code").first().getAttribute("title").catch(() => null);
    const row = {
      label, run_id: runId, status_page: pageStatus, status_api: st.status,
      document_sha256: rep.document.id, questions_md_sha256: qsha, version_on_page: versionOnPage,
      first_question: rep.questions[0] && rep.questions[0].id + " " + rep.questions[0].prompt,
    };
    res.checks.push(row);
    check(pageStatus === st.status, `${label}: статус на странице = статус запуска (${st.status})`);
    check(qsha === rep.document.id, `${label}: questions.md относится к версии ${rep.document.id.slice(0, 12)}`);
    if (versionOnPage) check(versionOnPage === rep.document.id, `${label}: вопросы на странице — той же версии`);
    return { st, rep };
  }

  try {
    // 0. Режим виден в шапке до загрузки.
    await page.goto(base + "/");
    res.mode_line = await page.locator("header .engine").innerText();
    check(/mock-провайдер движка: ответы модели воспроизводятся из записанного сценария/.test(res.mode_line), "режим mock и сценарий показаны в шапке");

    // 1. Загрузка и прогресс; обновление страницы посреди прогона.
    await page.setInputFiles("#upload-input", doc);
    await page.waitForURL(/\/runs\/\d{8}-\d{6}-[0-9a-f]{6}$/);
    res.rev1 = runIdOf(page.url());
    res.rev1_status_seen = [await page.getAttribute("body", "data-run-status")];
    await page.reload();
    res.rev1_status_seen.push(await page.getAttribute("body", "data-run-status"));
    await frame("1-progress", "Загрузка: этапы движка по мере работы; страница обновлена посреди прогона");
    await page.waitForSelector(FINAL, { timeout: 120000 });
    res.rev1_status_seen.push(await page.getAttribute("body", "data-run-status"));
    const v1 = await sameVersion(res.rev1, "редакция 1");

    // 2. Замечание с цитатой — то, о котором вопрос Q-01.
    const q1 = v1.rep.questions[0];
    const fid = q1.finding_ids[0];
    const fin = page.locator(`details[id="${fid}"]`);
    if (!(await fin.evaluate((el) => el.open))) await fin.locator("summary").click();
    await fin.scrollIntoViewIfNeeded();
    check((await fin.locator("figure.fragment mark").count()) >= 1, `замечание ${fid} открыто, цитата подсвечена`);
    res.finding = { id: fid, title: (await fin.locator("summary").innerText()).replace(/\s+/g, " ") };
    await frame("2-finding", `Замечание ${fid} с цитатой и местом в документе`, fin);

    // 3. Ответ владельца: демонстрационный ответ с новой формулировкой пункта.
    const q = page.locator(`#q-${q1.id}`);
    await q.scrollIntoViewIfNeeded();
    await q.locator(".demo-fill").click();
    res.answer = { question: q1.id + " " + q1.prompt, text: await page.inputValue(`#a_${q1.id}`),
      wording: await page.inputValue(`#w_a_${q1.id}`).catch(() => ""), provenance: await page.locator(`#prov_a_${q1.id}`).innerText() };
    check(res.answer.wording.length > 0, "поле «Новая формулировка» заполнено");
    await frame("3-owner-answer", "Ответ владельца: вопрос, предложение, которое будет заменено, новая формулировка, происхождение ответа", q);
    await Promise.all([page.waitForURL((u) => !u.toString().includes(res.rev1)), page.click("#confirm")]);
    res.rev2 = runIdOf(page.url());
    res.rev2_status_seen = [await page.getAttribute("body", "data-run-status")];
    await page.reload();
    res.rev2_status_seen.push(await page.getAttribute("body", "data-run-status"));
    await page.waitForSelector(FINAL, { timeout: 120000 });
    res.rev2_status_seen.push(await page.getAttribute("body", "data-run-status"));

    // 4. Изменённый пункт после повторной проверки.
    const v2 = await sameVersion(res.rev2, "редакция 2");
    const changes = page.locator("#changes");
    check((await changes.count()) === 1, "блок «Изменённые пункты» на странице новой редакции");
    res.changed = (await changes.innerText()).replace(/\s+/g, " ");
    check(res.changed.includes(res.answer.wording), "в изменённом пункте — новая формулировка владельца");
    check(v2.rep.document.id !== v1.rep.document.id, "у новой редакции свой SHA документа");
    check(v2.st.input.sha256 === v1.rep.document.id, "новая редакция проверяла ту версию, на вопрос которой ответили");
    await changes.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => window.scrollBy(0, -24));
    await frame("4-changed-clause", "Повторная проверка: изменённый пункт «было → стало» в новой версии, сравнение с редакцией 1");

    // 5. Скачивание результата новой редакции.
    const files = page.locator("#downloads");
    await files.scrollIntoViewIfNeeded();
    res.downloads = [];
    for (const name of ["report.md", "report.html", "report.annotated.pdf"]) {
      const link = files.locator(`a[download]:text-is("${name}")`);
      if (!(await link.count())) continue;
      const [dl] = await Promise.all([page.waitForEvent("download"), link.click()]);
      const saved = path.join(out, "rev2-" + name);
      await dl.saveAs(saved);
      res.downloads.push({ name, bytes: fs.statSync(saved).size, sha256: sha(fs.readFileSync(saved)) });
    }
    const revLink = files.locator('a[download]', { hasText: ".rev-" }).first();
    const [rdl] = await Promise.all([page.waitForEvent("download"), revLink.click()]);
    const revSaved = path.join(out, "rev2-" + (await revLink.innerText()));
    await rdl.saveAs(revSaved);
    res.revision_file = { name: path.basename(revSaved), sha256: sha(fs.readFileSync(revSaved)) };
    check(res.revision_file.sha256 === v2.rep.document.id, "скачанный файл редакции — та же версия, что в отчёте и вопросах");
    const mdText = fs.readFileSync(path.join(out, "rev2-report.md"), "utf8");
    check(mdText.includes(res.rev2) || mdText.includes(v2.rep.document.id.slice(0, 12)) || mdText.length > 0, "report.md скачан");
    await frame("5-downloads", "Скачивание: отчёт, HTML №13, PDF с выделениями №14 и файл редакции этой версии", files);

    // 6. Прежняя ссылка на первую версию.
    await page.goto(base + "/runs/" + res.rev1);
    check((await page.locator("#stale").count()) === 1, "прежняя ссылка открывает редакцию 1 с пометкой «не актуальная»");
    check((await page.locator(`#not-latest a[href="/runs/${res.rev2}"]`).count()) === 1, "пометка о неактуальной редакции — вверху страницы");
    await page.evaluate(() => window.scrollTo(0, 0));
    const old = await sameVersion(res.rev1, "прежняя ссылка на редакцию 1");
    check(old.rep.document.id === v1.rep.document.id, "по прежней ссылке — данные версии 1, а не версии 2");
    check((await page.locator(`#stale a[href="/runs/${res.rev2}"]`).count()) === 1, "есть ссылка на актуальную редакцию");
    await frame("6-old-link", "Прежняя ссылка: версия 1 со своими статусом, вопросами и файлами, ссылка на актуальную редакцию");

    res.log = log;
    fs.writeFileSync(path.join(out, "demo.json"), JSON.stringify(res, null, 1));
    console.log(JSON.stringify(res));
  } catch (err) {
    await page.screenshot({ path: path.join(out, "zz-failure.png"), fullPage: true }).catch(() => {});
    console.log(JSON.stringify({ error: String((err && err.stack) || err), log, res }));
    process.exitCode = 1;
  } finally {
    await ctx.close();
    await browser.close();
  }
})();
