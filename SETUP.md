# Leha - Setup & Run

Personal voice assistant for this Windows laptop.

## What got built

```text
D:\jarvis\
  jarvis_ai\
    main.py            # compatibility entry; launches listen.py
    config.py          # all settings: models, thresholds, names
    wake.py            # legacy openwakeword path
    ears.py            # speech to text
    mouth.py           # text to speech: PowerShell or Piper
    brain.py           # Groq brain with local Ollama fallback
    assistant_core.py  # fast local reflex/intents
    assistant_session.py # wake word and follow-up session gate
    memory.py          # remembers facts across sessions
    telegram_bot.py    # phone bridge
    skills/            # laptop and phone control tools
  setup_check.py       # pre-flight verification
  requirements.txt
```

## One-time setup

1. Install Python deps:
   ```powershell
   pip install -r requirements.txt
   ```
2. Install Ollama from ollama.com, then pull the local fallback brain:
   ```powershell
   ollama pull qwen2.5:3b
   ```
3. Verify everything:
   ```powershell
   python setup_check.py
   ```

## Run the voice assistant

```powershell
cd D:\jarvis
python -m jarvis_ai.main
```

This launches the maintained always-on listener in `jarvis_ai.listen`.

## Cloudflare Primary Brain

Leha supports this response order when Cloudflare is enabled:

```text
Cloudflare Workers AI -> Groq -> OpenAI -> local Ollama
```

For safety, Cloudflare is disabled until a fresh API token is configured. Create
a new restricted Cloudflare token with Workers AI permission, then save only the
token in `D:\jarvis\.cloudflare_token`. Set these Windows environment values
before restarting Leha:

```powershell
[Environment]::SetEnvironmentVariable('CLOUDFLARE_ACCOUNT_ID', 'your-account-id', 'User')
[Environment]::SetEnvironmentVariable('CF_BRAIN_ENABLED', '1', 'User')
```

Do not put tokens in `config.py`, Git, chat messages, or screenshots. A token
that was shared outside your machine should be revoked and replaced first.

Say **"Leha"**, wait for **"Yes, Sir?"**, then speak a command:

- "What time is it?"
- "Open Chrome and search for mango leaf disease."
- "Play Ilayaraja music Telugu."
- "Play Raja songs on Spotify."
- "Close YouTube tab."
- "Close Chrome."
- "Close anything."
- "What's my battery level?"
- "Brief me."
- "Weather today."
- "Remember that I wake up at 5 AM."
- "Lock the laptop."

While music or YouTube is playing, these playback controls work without saying Leha:

- "stop" / "pause"
- "resume" / "continue"
- "next" / "previous"
- "volume up" / "volume down"

To exit Leha, say "goodbye" or "stop listening", or press Ctrl+C.

Say **"Leha health"** to hear a short status for the microphone, ears, brain,
listener state, plus the last measured provider/timing after a completed turn.

## Start Automatically With Windows

Run this once:

```powershell
cd D:\jarvis
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

The installer first tries a Windows Scheduled Task. If Windows blocks that for
your account, it safely installs a per-user Startup-folder launcher instead.
Both launch the supervised listener after sign-in.

Optional owner voice profile:

1. Say "Leha train my voice".
2. Confirm with "Leha voice profile".
3. To require this rough voice match for addressed commands, set
   `SPEAKER_VERIFY_ENABLED = True` in `jarvis_ai/config.py`.

## Ultra Beast Mode

Leha now follows a Siri/Alexa-style control loop:

- always-open mic stream with dynamic noise calibration
- fuzzy wake word for "Leha" and common Whisper mishearings
- short follow-up window after wake/reply
- fast local reflexes for media, volume, timers, app launch, and time
- fast local answers for date, battery/system status, weather, reminders, and briefings
- optional rough owner voice profile for basic speaker gating
- LLM brain only when the local reflex layer cannot handle the request
- same session logic in native voice mode and browser voice mode

## Browser mic mode

If the Windows mic path is unreliable, use the browser mic:

```powershell
python -m jarvis_ai.webserver
```

Then open:

```text
http://127.0.0.1:8001
```

## Android bridge

1. Telegram: message **@BotFather**, run `/newbot`, and copy the token.
2. Get your numeric id from **@userinfobot**.
3. Edit `jarvis_ai/config.py` and put your id in `TELEGRAM_ALLOWED_USERS`.
4. Set token and run:
   ```powershell
   set JARVIS_TG_TOKEN=<your-token>
   python -m jarvis_ai.telegram_bot
   ```

## Android control

1. Phone: Settings -> About phone -> tap **Build number** 7 times -> enable **USB debugging**.
2. Install Android platform-tools and scrcpy. Put `adb` on PATH or set `ADB_PATH` in config.py.
3. Connect by USB and verify:
   ```powershell
   adb devices
   ```
4. Voice examples: "Leha, take a screenshot on my phone", "open WhatsApp on my phone".

## Google Maps

Google Maps directions work without saving a Google password or API key. Try:

- "Leha, navigate to Chennai airport"
- "Leha, find restaurants near me on Google Maps"

Leha opens a Google Maps URL in your browser. Gmail, Calendar, Drive, and
Contacts require a separate Google OAuth desktop-client setup; do not put your
Google account password in this project.

## Google Calendar, Drive, and Contacts

1. Save the Google Desktop OAuth client JSON as `D:\jarvis\google_credentials.json`.
2. Run the authorization once. A browser window opens for Google consent:

   ```powershell
   python -m jarvis_ai.google_auth
   ```

3. The local `google_token.json` is created after approval. It is private and
   ignored by Git. Leha can then use the Google Calendar, Drive, and Contacts tools.

## Better ears (speech-to-text)

Leha now supports four speech-to-text engines:

```text
auto      Deepgram -> OpenAI -> Groq -> local Whisper
deepgram  Deepgram Nova cloud transcription
openai    OpenAI transcription API
groq      Groq Whisper transcription
local     Faster-Whisper on the laptop
```

To use Deepgram, put its API key in `D:\jarvis\.deepgram_key` or set it for
the current terminal session:

```powershell
$env:DEEPGRAM_API_KEY = "your-key"
$env:STT_ENGINE = "deepgram"
```

To use OpenAI transcription, put the key in `D:\jarvis\.openai_key` or set:

```powershell
$env:OPENAI_API_KEY = "your-key"
$env:STT_ENGINE = "openai"
```

Leave `STT_ENGINE` unset or set it to `auto` to prefer Deepgram when its key is
available, then OpenAI, then Groq, then local Whisper. Restart Leha after any
key or engine change.

## Optional better voice

Leha uses Edge neural TTS for live instant replies:

```python
TTS_ENGINE = "edge"
EDGE_TTS_VOICE = "en-US-AvaMultilingualNeural"
EDGE_TTS_RATE = "-3%"
```

This is the practical live voice on this CPU-only laptop. It is human-sounding
and responds quickly.

Audition samples are saved here:

```text
jarvis_ai/voices/edge_auditions/ava_multilingual.mp3
jarvis_ai/voices/edge_auditions/emma_multilingual.mp3
jarvis_ai/voices/edge_auditions/jenny.mp3
jarvis_ai/voices/edge_auditions/neerja_expressive.mp3
jarvis_ai/voices/edge_auditions/libby.mp3
```

If you prefer one of those files, set `EDGE_TTS_VOICE` in
`jarvis_ai/config.py` to the matching voice name.

Reference-audio cloning is wired through Chatterbox for offline/slow use:

```python
TTS_ENGINE = "clone"
CLONE_TTS_REFERENCE = "jarvis_ai/voices/leha_reference_mix.wav"
```

The prepared reference file is `jarvis_ai/voices/leha_reference_mix.wav`,
generated from both MP3 samples. On this CPU-only laptop, a short cloned reply
takes about 50 seconds. A CUDA GPU machine should be much faster.

Voice cloning options tested on this laptop:

- Edge neural voice: instant enough for daily use, but not cloned.
- Chatterbox: true reference-audio cloning from your samples; generated
  `jarvis_ai/voices/leha_clone_mix_test.wav`; about 49 seconds for a short reply.
- OpenVoice: tone-color conversion using your samples; generated
  `jarvis_ai/voices/openvoice_clone_test.wav`; about 29 seconds for a 12-second
  source clip after downloads.
- Coqui/XTTS: package install failed on this Windows setup because Microsoft C++
  Build Tools are missing for a native extension.
- Piper: fast local TTS, but custom voice training needs a transcribed dataset
  and a training workflow, usually on GPU/Colab.

For instant conversation, keep `TTS_ENGINE = "edge"`. For offline cloned samples,
use `jarvis_ai.voice_clone` or OpenVoice CLI.

## Hugging Face instant voice

Hugging Face can be instant only with a dedicated warm GPU Inference Endpoint.
Serverless/free inference can cold-start and feel slow.

Configure a Hugging Face endpoint that returns audio bytes for a text payload,
then set:

```powershell
set HF_TOKEN=<your-token>
set HF_TTS_ENDPOINT_URL=https://<your-endpoint>
```

Then in `jarvis_ai/config.py`:

```python
TTS_ENGINE = "hf"
HF_TTS_FALLBACK_TO_EDGE = True
```

Test it without starting the assistant:

```powershell
python test_hf_tts.py
```

If the endpoint is warm and GPU-backed, Leha can speak quickly through Hugging
Face. If it is cold or serverless, Edge voice will still be faster.

## Colab/Kaggle voice cloning

Use this when the stock live voice does not match your uploaded audio.

Colab/Kaggle GPU is good for generating and testing cloned samples:

```powershell
python tools/prepare_voice_gpu_bundle.py
```

Then open:

```text
notebooks/leha_chatterbox_gpu_colab.ipynb
```

Upload `voice_gpu_bundle.zip`, enable GPU, run all cells, and download
`leha_gpu_outputs.zip`.

Install the downloaded samples locally:

```powershell
python tools/install_voice_gpu_outputs.py path\to\leha_gpu_outputs.zip
```

This helps you find the best Chatterbox settings for the uploaded voice. It does
not make live laptop replies instant by itself. For instant live cloned voice,
keep the GPU running as a Hugging Face/Colab/Kaggle-style endpoint and set
`TTS_ENGINE = "hf"`.

Local Piper option:

1. Install Piper:
   ```powershell
   pip install piper-tts
   ```
2. Download a voice into `jarvis_ai/voices/`.
3. Set `TTS_ENGINE = "piper"` in `jarvis_ai/config.py`.

## Honest limits

- True Siri/Alexa far-field performance needs acoustic echo cancellation and better mic hardware.
- Loud YouTube audio through speakers can still confuse any normal laptop/headset mic.
- Brain fallback runs on CPU, so keep spoken answers short for best speed.

## Offline "Leha" wake word (no Picovoice account)

Picovoice's current console requires a company-email trial, so it is optional.
Leha can instead use a locally trained openWakeWord ONNX model with no API key
and no cloud audio upload.

1. Record private wake clips:
   ```powershell
   python tools/record_leha_wake_samples.py --count 30
   ```
   Say the prompts naturally in a quiet room. The clips remain ignored by Git.
2. Train/export an openWakeWord-compatible `leha.onnx` model on a GPU machine.
   A reliable model needs positive Leha clips plus negative/background speech;
   this cannot be replaced by a few copied recordings.
3. Put the exported file somewhere private, for example
   `jarvis_ai/voices/leha.onnx`, then set:
   ```python
   OWW_MODEL_PATH = r"jarvis_ai/voices/leha.onnx"
   OWW_ENABLED = True
   ```
4. Restart Leha. Its startup log must say `[wake] engine: openwakeword`.

Until `leha.onnx` exists, Leha deliberately stays on the existing Deepgram
transcript wake path. Enabling the bundled `hey_jarvis` model would make the
assistant listen for the wrong name.

## Private Leha Wake-Word Workflow

The local `leha_wake_model.onnx` remains disabled until it passes a real
false-wake evaluation. Do not enable it based only on training accuracy.

1. Record at least 40 positive wake clips:
   ```powershell
   python tools/record_leha_wake_samples.py --count 50 --output jarvis_ai/voices/wake_leha_new
   ```
2. Record at least 100 negative clips. Do **not** say Leha; include normal
   conversation, TV/music, and room noise:
   ```powershell
   python tools/record_leha_wake_negatives.py --count 120
   ```
3. Package the private data for the GPU training job:
   ```powershell
   python tools/prepare_leha_wake_training_bundle.py
   ```
4. Train with the updated private Kaggle job, download its ONNX output, then
   evaluate it on recordings not used for training:
   ```powershell
   python tools/evaluate_leha_wake_model.py `
     --positive jarvis_ai/voices/wake_leha_eval `
     --negative jarvis_ai/voices/wake_negative_eval
   ```
5. Only after the evaluation reports at least 95% wake recall and at most 1%
   false wakes should `CUSTOM_WAKE_ENABLED` be changed to `True`.
