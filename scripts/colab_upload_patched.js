const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const notebook = path.join(repo, "kaggle_wake_job", "train_leha_oww.ipynb");

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
  await page.goto("https://colab.research.google.com/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_upload_home.png"), fullPage: false });
  await page.getByText("Upload", { exact: true }).click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_upload_tab.png"), fullPage: false });
  const chooserPromise = page.waitForEvent("filechooser", { timeout: 30000 });
  const fileInput = page.locator('input[type="file"]').first();
  if (await fileInput.count()) {
    await fileInput.setInputFiles(notebook);
  } else {
    await page.getByText(/browse|choose|upload/i).first().click();
    const chooser = await chooserPromise;
    await chooser.setFiles(notebook);
  }
  await page.waitForTimeout(10000);
  await page.screenshot({ path: path.join(repo, "logs", "colab_uploaded_patched.png"), fullPage: false });
  console.log(page.url());
  await context.close();
})();
