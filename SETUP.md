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
