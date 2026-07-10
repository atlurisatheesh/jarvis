const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const downloadDir = path.join(repo, "kaggle_wake_job", "downloaded_outputs");
fs.mkdirSync(downloadDir, { recursive: true });

const notebookUrl =
  process.env.COLAB_NOTEBOOK_URL ||
  "https://colab.research.google.com/drive/1FDKG2uCB4O4hYAZYYt4D9jzxTPHr3Esa";

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

(async () => {
  log(`Opening ${notebookUrl}`);
  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: "chrome",
    headless: false,
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
    args: ["--start-maximized"],
  });
  const page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto(notebookUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(10000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_uploaded_opened.png"), fullPage: false });

  log("Starting Run all");
  const downloadPromise = page.waitForEvent("download", { timeout: 90 * 60 * 1000 }).catch((error) => {
    log(`DOWNLOAD_WAIT_FAILED ${error.message}`);
    return null;
  });
  await page.mouse.click(360, 84);
  await page.waitForTimeout(3000);
  for (const label of ["Run anyway", "Run all", "Yes", "OK", "Continue"]) {
    try {
      const button = page.getByText(label, { exact: true }).last();
      if (await button.isVisible({ timeout: 1500 })) {
        await button.click({ force: true });
        log(`Clicked confirmation: ${label}`);
        await page.waitForTimeout(2000);
      }
    } catch {
      // dialog not present
    }
  }
  await page.screenshot({ path: path.join(repo, "logs", "colab_uploaded_run_started.png"), fullPage: false });

  const download = await downloadPromise;
  await page.screenshot({ path: path.join(repo, "logs", "colab_uploaded_run_done.png"), fullPage: false });
  if (!download) {
    await context.close();
    process.exit(2);
  }
  const target = path.join(downloadDir, download.suggestedFilename());
  await download.saveAs(target);
  log(`Downloaded ${target}`);
  await context.close();
})();
