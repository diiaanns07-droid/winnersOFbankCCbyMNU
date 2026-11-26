// Путь аналитика в настоящем Chromium. Запускается из tests/p15/test_browser.py.
// Аргументы: BASE_URL CASE_PATH OUT_DIR. Результат — JSON в stdout, код 0 при успехе.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [base, casePath, outDir] = process.argv.slice(2);
const log = [];
function check(cond, msg) {
  if (!cond) throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg);
  log.push("ok: " + msg);
}

async function waitFinal(page, status) {
  await page.waitForSelector(`body[data-run-status="${status}"]`, { timeout: 30000 });
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1200, height: 900 } });
  const page = await ctx.newPage();
  const shot = (name) => page.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true });
  const result = {};
  try {
    // 1. Одна кнопка загрузки.
    await page.goto(base + "/");
    check((await page.locator("#upload-input").count()) === 1, "на главной одна кнопка загрузки");
    await shot("01-home");
    await page.setInputFiles("#upload-input", casePath);
    await page.waitForURL(/\/runs\/\d{8}-\d{6}-[0-9a-f]{6}$/);
    result.parent = page.url().split("/runs/")[1];
    await waitFinal(page, "complete");
    // 2. Вердикт.
    const verdict = await page.locator("#verdict").innerText();
    check(verdict.includes("нельзя начинать"), "вердикт показан: нельзя начинать");
    await shot("02-verdict");
    // 3. Два фрагмента замечания-конфликта.
    const f1 = page.locator("details#F-001");
    check(await f1.evaluate((el) => el.open), "критичное замечание раскрыто");
    const frags = f1.locator("figure.fragment");
    check((await frags.count()) === 2, "у конфликта два фрагмента");
    check((await f1.locator("mark").count()) === 2, "обе цитаты подсвечены");
    const labels = await f1.locator(".flabel").allInnerTexts();
    check(labels.join(",") === "А,Б", "фрагменты подписаны А и Б");
    await f1.scrollIntoViewIfNeeded();
    await f1.screenshot({ path: path.join(outDir, "03-fragments.png") });
    // 4. Ответ: демонстрационный (с подписью происхождения) + вариант решения движка.
    await page.click('#q-Q-01 .demo-fill');
    const prov = await page.locator("#prov_a_Q-01").innerText();
    check(prov.includes("демонстрационный ответ команды"), "подпись происхождения демо-ответа видна");
    await page.check('input[name="d_Q-03"][value="1"]');
    check((await page.inputValue("#a_Q-03")).startsWith("400 Bad Request"), "вариант решения подставил текст");
    await page.locator("#action").screenshot({ path: path.join(outDir, "04-answer.png") });
    // 5. Подтверждение двойным кликом.
    await Promise.all([page.waitForURL((u) => !u.toString().includes(result.parent)), page.dblclick("#confirm")]);
    result.child = page.url().split("/runs/")[1].split("?")[0];
    check(result.child !== result.parent, "создана новая редакция");
    await waitFinal(page, "complete");
    // 6. Сравнение и что ещё требует внимания.
    const cmp = await page.locator("#compare-summary").innerText();
    check(/Устранено: 2/.test(cmp), "в сравнении устранено 2 замечания");
    const att = await page.locator("#attention").innerText();
    check(att.includes("Q-02"), "в «что ещё требует внимания» остался открытый вопрос Q-02");
    const answersProv = await page.locator("#compare-summary .provenance").innerText();
    check(answersProv.includes("демонстрационный ответ команды") && answersProv.includes("вариант 1"), "происхождение ответов редакции показано");
    await shot("05-revision");
    await page.click("text=Открыть сравнение");
    await page.waitForURL(/\/compare$/);
    check((await page.locator("#diff").innerText()).includes("Устранены (2)"), "страница сравнения: diff №09");
    await shot("06-compare");
    // Исходный и обновлённый отчёты открываются.
    for (const rid of [result.parent, result.child]) {
      const resp = await page.request.get(`${base}/runs/${rid}/files/report.md?inline=1`);
      check(resp.ok() && (await resp.text()).includes("# Отчёт о проверке требований"), `report.md открывается для ${rid}`);
    }
    const htmlTab = await ctx.newPage();
    await htmlTab.goto(`${base}/runs/${result.child}/files/report.html?inline=1`);
    check((await htmlTab.content()).includes("MOCK HTML"), "HTML-отчёт (место №13) открывается");
    await htmlTab.close();
    // 7. Скачивание реальных файлов.
    await page.goto(`${base}/runs/${result.child}`);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click('#downloads a[download]:text-is("report.md")')]);
    const saved = path.join(outDir, "downloaded-report.md");
    await dl.saveAs(saved);
    result.downloaded = saved;
    const [qdl] = await Promise.all([page.waitForEvent("download"), page.click("text=Скачать questions.md")]);
    const qsaved = path.join(outDir, "questions.md");
    await qdl.saveAs(qsaved);
    check(fs.readFileSync(qsaved, "utf8").includes("## Q-02"), "questions.md скачан и содержит открытый вопрос");
    // 8. Старая редакция: решения туда не принимаются.
    await page.goto(`${base}/runs/${result.parent}`);
    check((await page.locator("#stale").count()) === 1, "старая редакция предупреждает об актуальной");
    // 9. Перезагрузка страницы во время задания.
    await page.goto(base + "/");
    const slow = path.join(outDir, "case_ab__slow.md");
    fs.copyFileSync(casePath, slow);
    await page.setInputFiles("#upload-input", slow);
    await page.waitForSelector('body[data-run-status="running"]', { timeout: 15000 });
    await page.waitForSelector("#stages li.done", { timeout: 15000 });
    await page.reload();
    check((await page.getAttribute("body", "data-run-status")) === "running", "после перезагрузки статус running");
    check((await page.locator("#stages li.done").count()) >= 1, "после перезагрузки видны завершённые этапы");
    await shot("07-running-reload");
    await waitFinal(page, "complete");
    // 10. Нет ключа → понятная причина → проверка по правилам.
    await page.goto(base + "/");
    const nokey = path.join(outDir, "case_ab__no_key.md");
    fs.copyFileSync(casePath, nokey);
    await page.setInputFiles("#upload-input", nokey);
    await waitFinal(page, "failed");
    check((await page.locator("#error").innerText()).includes("ANTHROPIC_API_KEY"), "причина ошибки: нет ключа");
    await shot("08-no-key");
    await page.click("text=Проверить только по правилам (без LLM)");
    await waitFinal(page, "partial");
    check((await page.locator("#incomplete").innerText()).includes("только правила"), "отчёт помечен неполным, режим — только правила");
    await shot("09-rules-only");
    result.log = log;
    console.log(JSON.stringify(result));
  } catch (err) {
    await shot("zz-failure").catch(() => {});
    console.log(JSON.stringify({ error: String(err && err.stack || err), log }));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
