// Rasterise every NNNN.svg in a directory to NNNN.png with headless Chromium.
// Usage: node svg2png.js <dir>
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const dir = process.argv[2];
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".svg")).sort();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1800, height: 1200 } });
  for (const f of files) {
    await page.setContent(fs.readFileSync(path.join(dir, f), "utf8"));
    const svg = await page.$("svg");
    await svg.screenshot({ path: path.join(dir, f.replace(/\.svg$/, ".png")) });
  }
  await browser.close();
})();
