const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const downloadDir = path.join(repo, "kaggle_wake_job", "downloaded_outputs");
fs.mkdirSync(downloadDir, { recursive: true });

const notebookUrl =
  "https://colab.research.google.com/drive/1dKr6n8ZHy_rc_xl7K2IlmCi78T1e8prT";

const code = `
from google.colab import files
import os, zipfile, glob
candidates = []
for root in ['/content', '/content/leha_oww_out', '/content/leha_wake_out', '/content/openWakeWord']:
    candidates.extend(glob.glob(root + '/**/leha.onnx', recursive=True))
    candidates.extend(glob.glob(root + '/**/hey_leha.onnx', recursive=True))
    candidates.extend(glob.glob(root + '/**/leha_wake_models.zip', recursive=True))
print('FOUND:', candidates)
zip_path = '/content/leha_wake_models.zip'
if not os.path.exists(zip_path):
    model_paths = []
    for name in ['leha.onnx', 'hey_leha.onnx']:
        matches = [p for p in candidates if os.path.basename(p) == name]
        if matches:
            model_paths.append(matches[0])
    print('MODEL_PATHS:', model_paths)
    if len(model_paths) >= 2:
        with zipfile.ZipFile(zip_path, 'w') as z:
            for p in model_paths:
                z.write(p, os.path.basename(p))
print('ZIP_EXISTS:', os.path.exists(zip_path), os.path.getsize(zip_path) if os.path.exists(zip_path) else 'missing')
files.download(zip_path)
`.trim();

(async () => {
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
  await page.waitForTimeout(8000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_reopened.png"), fullPage: false });

  await page.mouse.click(700, 700);
  await page.keyboard.press("Control+End");
  await page.waitForTimeout(1000);
  await page.keyboard.press("Control+M");
  await page.waitForTimeout(300);
  await page.keyboard.press("B");
  await page.waitForTimeout(1000);
  await page.keyboard.insertText(code);
  await page.waitForTimeout(500);

  const downloadPromise = page.waitForEvent("download", { timeout: 120000 }).catch((error) => {
    console.error("DOWNLOAD_WAIT_FAILED", error.message);
    return null;
  });
  try {
    const runButtons = page.locator("colab-run-button");
    const count = await runButtons.count();
    if (count > 0) {
      await runButtons.nth(count - 1).click({ force: true, timeout: 5000 });
    } else {
      throw new Error("No colab-run-button elements found");
    }
  } catch (error) {
    console.error("RUN_BUTTON_SELECTOR_FAILED", error.message);
    await page.mouse.click(132, 421);
  }
  const download = await downloadPromise;
  await page.screenshot({ path: path.join(repo, "logs", "colab_download_attempt.png"), fullPage: false });
  if (!download) {
    await context.close();
    process.exit(2);
  }
  const target = path.join(downloadDir, download.suggestedFilename());
  await download.saveAs(target);
  console.log(target);
  await context.close();
})();
