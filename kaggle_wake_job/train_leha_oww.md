# Train Custom "Leha" Wake Word — openWakeWord (Google Colab)

Trains **two** custom openWakeWord models so you can say **"Leha"** or **"Hey Leha"** to wake your assistant — fully offline, no API key, no account.

---

## Quick Start (5 steps)

### 1. Open the notebook in Colab

Click this link (or upload `train_leha_oww.ipynb` from this folder):

👉 **[Open in Google Colab](https://colab.research.google.com/?filepath=/kaggle_wake_job/train_leha_oww.ipynb)**

If the link doesn't auto-load the file: go to [colab.research.google.com](https://colab.research.google.com) → **File → Upload notebook** → select `train_leha_oww.ipynb` from this folder.

### 2. Enable GPU (free)

**Runtime → Change runtime type → Hardware accelerator → T4 GPU → Save**

### 3. Run all

**Runtime → Run all** (or `Ctrl+F9`)

Total time: **~30–45 minutes**. You don't need to watch it — go do something else.

What happens automatically:
- Installs Piper TTS + openWakeWord training deps (~5 min)
- Downloads background noise, room impulse responses, music (~10 min)
- Generates ~2,000 synthetic "leha" clips via TTS (~5 min)
- Trains `leha` model on GPU (~10 min)
- Generates ~2,000 synthetic "hey leha" clips (~5 min)
- Trains `hey_leha` model on GPU (~10 min)
- Verifies both models load + predict

### 4. Download the two `.onnx` files

In Colab, click the 📁 folder icon (left sidebar):
- Find `/content/leha.onnx` → right-click → **Download**
- Find `/content/hey_leha.onnx` → right-click → **Download**

(Or download `/content/leha_wake_models.zip` for both at once.)

### 5. Install on your laptop

Copy both files into:
```
D:\jarvis\jarvis_ai\voices\
```

Then run:
```powershell
cd D:\jarvis
.\scripts\install_leha_wake_model.ps1
```

Restart Leha. Say **"Leha"** or **"Hey Leha"** — done.

---

## How it works

| Step | What happens |
|---|---|
| **Synthetic TTS** | Piper TTS generates ~2,000 clips of different voices saying "leha" / "hey leha" |
| **Augmentation** | Clips get noise, reverb, gain variation, speed perturbation (realistic variation) |
| **Negative data** | ~2,000 hours of pre-computed background speech features (ACAV100M) teach the model what *not* to trigger on |
| **Training** | openWakeWord's neural model trains on GPU for ~10k steps |
| **Output** | `.onnx` files (~2 MB each) — the same format as the built-in "hey jarvis" model |

This is the **same pipeline** openWakeWord uses to train all its official models. No real recordings needed — synthetic TTS gives enough variation for a strong model.

---

## Troubleshooting

### "Piper sample generator failed to clone"
Colab occasionally blocks the git clone. Re-run just that cell (Cell 1). If it persists, the install cell at the top has all the install commands — run them one at a time.

### "CUDA out of memory"
Reduce `n_samples` from 2000 → 1000 in the `train_phrase(...)` calls (Sections 4 and 5). Slightly lower accuracy but trains fine.

### Training is slow / no GPU
Confirm Runtime → Change runtime type → T4 GPU. Free tier sometimes assigns CPU; wait a bit and retry.

### Model didn't reach target accuracy
The training prints final accuracy and recall metrics. If recall < 0.2, increase `steps` to 15000 and re-run. The model is still usable at lower accuracy — just set `OWW_THRESHOLD` lower in config (e.g., 0.3).

### `install_leha_wake_model.ps1` says files not found
Make sure both `.onnx` files are in `D:\jarvis\jarvis_ai\voices\` and named exactly `leha.onnx` and `hey_leha.onnx`.

---

## File outputs

| File | Purpose | Goes to |
|---|---|---|
| `leha.onnx` | Single-word "Leha" wake model | `jarvis_ai/voices/leha.onnx` |
| `hey_leha.onnx` | Two-word "Hey Leha" wake model | `jarvis_ai/voices/hey_leha.onnx` |

After both are installed, openWakeWord loads **both** models simultaneously — either phrase wakes Leha.

---

## Why this is better than the old approach

| | Old: `wake_trainer.py` (abandoned) | New: openWakeWord Colab |
|---|---|---|
| Data source | Real recordings (needed 100+) | Synthetic TTS (auto-generated) |
| Best recall achieved | 44% | ~60%+ (openWakeWord baseline) |
| Effort | 30 min recording + manual cleanup | Click "Run all" |
| Architecture | Simple custom CNN | openWakeWord's production model |
| Used by | Just Leha | Home Assistant, Rhasspy, OVOS |
