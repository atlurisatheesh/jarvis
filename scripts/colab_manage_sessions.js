const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const notebookUrl =
  "https://colab.research.google.com/drive/1FDKG2uCB4O4hYAZYYt4D9jzxTPHr3Esa";

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
  await page.screenshot({ path: path.join(repo, "logs", "colab_sessions_before.png"), fullPage: false });
  await page.mouse.click(360, 84);
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_sessions_too_many.png"), fullPage: false });
  await page.getByText("Manage sessions", { exact: true }).click({ force: true });
  await page.waitForTimeout(5000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_sessions_manage.png"), fullPage: false });
  console.log("opened session manager");
  await context.close();
})();
