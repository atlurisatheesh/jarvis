const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const repo = "D:\\jarvis";
const userDataDir = path.join(repo, ".chrome-colab-profile");
const downloadDir = path.join(repo, "kaggle_wake_job", "downloaded_outputs");
fs.mkdirSync(downloadDir, { recursive: true });

const notebookUrl =
  "https://colab.research.google.com/drive/1dKr6n8ZHy_rc_xl7K2IlmCi78T1e8prT";

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

const code = `
import os, pathlib, site, shutil, zipfile, glob

print("Patching torch_audiomentations for modern Colab torchaudio...")
for root in site.getsitepackages():
    pkg = pathlib.Path(root) / 'torch_audiomentations'
    if not pkg.exists():
        continue
    for path in pkg.rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        new = text.replace('torchaudio.set_audio_backend("soundfile")', 'getattr(torchaudio, "set_audio_backend", lambda *a, **k: None)("soundfile")')
        new = new.replace("torchaudio.set_audio_backend('soundfile')", "getattr(torchaudio, 'set_audio_backend', lambda *a, **k: None)('soundfile')")
        if new != text:
            path.write_text(new, encoding='utf-8')
            print("patched", path)

print("Retraining Leha models...")
leha_path = train_phrase("leha", "leha", n_samples=2000, n_samples_val=1000, steps=10000)
hey_leha_path = train_phrase("hey leha", "hey_leha", n_samples=2000, n_samples_val=1000, steps=10000)

OUT = "/content" if os.path.isdir("/content") else os.getcwd()
final = []
for src, dst_name in [(leha_path, "leha.onnx"), (hey_leha_path, "hey_leha.onnx")]:
    if src and os.path.exists(src):
        dst = os.path.join(OUT, dst_name)
        shutil.copy(src, dst)
        final.append(dst)
        print("OK", dst, os.path.getsize(dst))
    else:
        print("MISSING", dst_name, src)

zip_path = os.path.join(OUT, "leha_wake_models.zip")
with zipfile.ZipFile(zip_path, "w") as z:
    for f in final:
        z.write(f, os.path.basename(f))

print("ZIP", zip_path, os.path.exists(zip_path), os.path.getsize(zip_path) if os.path.exists(zip_path) else "missing")
from google.colab import files
files.download(zip_path)
`.trim();

(async () => {
  log("Opening Colab");
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
  await page.screenshot({ path: path.join(repo, "logs", "colab_retrain_opened.png"), fullPage: false });

  log("Inserting recovery training cell");
  await page.mouse.click(700, 700);
  await page.keyboard.press("Control+End");
  await page.waitForTimeout(1000);
  await page.keyboard.press("Control+M");
  await page.waitForTimeout(300);
  await page.keyboard.press("B");
  await page.waitForTimeout(1000);
  await page.keyboard.insertText(code);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(repo, "logs", "colab_retrain_cell.png"), fullPage: false });

  log("Running recovery training cell");
  const downloadPromise = page.waitForEvent("download", { timeout: 75 * 60 * 1000 }).catch((error) => {
    log(`DOWNLOAD_WAIT_FAILED ${error.message}`);
    return null;
  });
  await page.mouse.click(132, 137);

  const download = await downloadPromise;
  await page.screenshot({ path: path.join(repo, "logs", "colab_retrain_done.png"), fullPage: false });
  if (!download) {
    await context.close();
    process.exit(2);
  }
  const target = path.join(downloadDir, download.suggestedFilename());
  await download.saveAs(target);
  log(`Downloaded ${target}`);
  await context.close();
})();
