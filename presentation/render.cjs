// Рендер слайдов deck.html в PNG 1600×900 (×2) через Playwright: node render.cjs deck.html out/
// Слайд с живым титулом рисуется по его финальному кадру (img), как при печати.
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const [deck, outDir] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2 });
  await page.goto("file://" + path.resolve(deck) + "#1");
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.addStyleTag({ content: "#s1 iframe{display:none!important}#s1 img{display:block!important}#nav{display:none!important}#stage{transform:none!important}#vp{display:block!important}" });
  const n = await page.evaluate(() => document.querySelectorAll(".slide").length);
  for (let i = 1; i <= n; i++) {
    await page.evaluate((k) => { location.hash = "#" + k; dispatchEvent(new KeyboardEvent("keydown", { key: "Home" })); for (let j = 1; j < k; j++) dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" })); }, i);
    await page.waitForTimeout(250);
    const file = path.join(outDir, "slide-" + String(i).padStart(2, "0") + ".png");
    await page.locator("#stage").screenshot({ path: file });
  }
  await browser.close();
  console.log(`${n} слайдов → ${outDir}`);
})();
