const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const notebookUrl =
  "https://colab.research.google.com/drive/1dKr6n8ZHy_rc_xl7K2IlmCi78T1e8prT";

(async () => {
  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: "chrome",
    headless: false,
    viewport: { width: 1440, height: 900 },
    args: ["--start-maximized"],
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(notebookUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(8000);
  await page.keyboard.press("Control+End");
  await page.waitForTimeout(2000);
  const text = await page.locator("body").innerText({ timeout: 30000 });
  const out = path.join(repo, "logs", "colab_body_text.txt");
  fs.writeFileSync(out, text, "utf8");
  await page.screenshot({ path: path.join(repo, "logs", "colab_text_extract.png"), fullPage: false });
  console.log(out);
  await context.close();
})();
