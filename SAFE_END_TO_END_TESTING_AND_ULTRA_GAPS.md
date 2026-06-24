# Leha Safe End-To-End Testing And Ultra Beast Gaps

## Important Rule

This guide is for testing only. It does **not** change Leha's existing code,
voice, model settings, wake settings, credentials, or device configuration.

Do not test these commands in this guide:

- shutdown, restart, sleep, hibernate, log off, or lock
- send email, SMS, WhatsApp, or make a phone call
- turn Wi-Fi off, eject USB, turn off display, or run shell commands
- delete, move, overwrite, or edit files
- purchases, account changes, payments, or anything external

The purpose is to confirm that Leha can listen, understand, answer, and do
safe reversible actions without duplicate voices or random replies.

## Before Testing

1. Make sure Leha is running:
   ```powershell
   cd D:\jarvis
   python -m jarvis_ai.health --json
   ```
2. Confirm the log contains:
   ```text
   Mic always open. Say 'Leha ...'
   [audio] capture rate ... Hz
   [heartbeat] state=idle
   ```
3. Keep speaker volume low for the first test. A headset is best until acoustic
   echo cancellation exists.
4. Close extra Leha terminals. There must be one supervisor and one listener.
5. Speak one command at a time. Wait until Leha finishes speaking before the
   next command because barge-in is not enabled yet.

## How To Record Results

For each test, record:

| Item | Record |
| --- | --- |
| Date/time | When the test happened |
| Command spoken | Exact words you said |
| Heard transcript | What the log printed after `[debug] heard:` |
| Result | Correct, incorrect, ignored, delayed, or duplicate voice |
| Delay | Approximate seconds from finishing speech to first Leha audio |
| Notes | Noise, music, headset/laptop mic, network state |

Use the same quiet-room and noisy-room tests after every major change. This
turns bugs into measurable problems instead of guesses.

## Test Group 1: Listener And Wake Gate

### 1.1 Background speech must be ignored

Speak normal sentences without saying Leha:

```text
I am checking my work today.
Lead generation is important.
Open Chrome.
What time is it?
```

Expected result: Leha stays silent. The log may show `ignored: no wake trigger`.

Pass: zero spoken Leha replies.

### 1.2 Direct addressed command

Say:

```text
Leha what time is it?
```

Expected result: one short time answer, one voice only.

Pass: Leha answers once and does not keep answering later room conversation.

### 1.3 Wake variation test

Try each phrase ten times, in a quiet room:

```text
Leha what is the date?
Hey Leha what is the date?
Leah what is the date?
```

Expected result: intended phrases wake Leha, unrelated phrases do not.

Pass target before enabling a dedicated wake model: record the actual success
rate. Do not lower matching thresholds only to make the number look better.

### 1.4 Post-reply safety

After Leha replies, speak an unrelated sentence without saying Leha.

Expected result: silence. Current follow-up mode is intentionally disabled.

Pass: no random response.

## Test Group 2: Speech Recognition

### 2.1 Short commands

Say:

```text
Leha what time is it?
Leha what is today's date?
Leha health.
Leha what can you access?
```

Expected result: transcript is close to the words spoken and answer is relevant.

### 2.2 Natural request

Say:

```text
Leha explain what artificial intelligence is in one sentence.
```

Expected result: one concise spoken answer.

### 2.3 Accent/noise test

Repeat one short command in these conditions:

- normal laptop microphone
- headset microphone
- low background music
- normal room conversation nearby

Expected result: a recorded comparison of accuracy and response delay. Do not
change providers during the test; compare the same configuration first.

## Test Group 3: Voice Output

### 3.1 One response only

Say:

```text
Leha tell me a short fact about space.
```

Expected result: exactly one female neural voice response.

Fail conditions:

- two voices
- same sentence repeated
- old delayed answer plays after a new answer
- voice stops in the middle without a new request

### 3.2 Long response continuity

Say:

```text
Leha explain the water cycle in three short sentences.
```

Expected result: complete answer with no overlap or cutoff.

### 3.3 Health response

Say:

```text
Leha health.
```

Expected result: microphone, ears, brain, and listener state are spoken once.

## Test Group 4: Safe Local Skills

These actions are reversible or read-only. Test one command at a time.

| Command | Expected safe result |
| --- | --- |
| `Leha open calculator` | Calculator opens once |
| `Leha open YouTube` | Browser opens YouTube once |
| `Leha close YouTube tab` | Current YouTube tab closes only |
| `Leha show desktop` | Windows are minimized/show desktop |
| `Leha dark mode` | Windows theme changes |
| `Leha light mode` | Windows theme changes back |
| `Leha volume up` | Volume increases |
| `Leha volume down` | Volume decreases |
| `Leha what is my battery status?` | Read-only status answer |
| `Leha top processes` | Read-only process summary |
| `Leha weather today` | Weather answer or a clear service error |

For media, test only the reversible controls:

```text
Leha play Ilayaraja Telugu music.
pause.
resume.
next.
previous.
```

Expected result: media controls work once, and plain `pause` does not wake the
assistant for unrelated speech.

## Test Group 5: Browser, Google, And Phone Read-Only Checks

### Browser

```text
Leha open Google Maps.
Leha search Google Maps for restaurants near me.
```

Expected result: a browser page or Maps search opens. Do not start navigation
or submit forms during this test.

### Google

Use read-only questions only:

```text
Leha what is on my calendar today?
Leha search my Drive for Leha roadmap.
Leha search Gmail for unread email.
```

Expected result: concise result or a clear OAuth/service error. Do not test
calendar creation or email sending here.

### Android

Connect the phone by USB with ADB first. Use only read-only or reversible tests:

```text
Leha phone status.
Leha take phone screenshot.
Leha open WhatsApp on my phone.
Leha go home on my phone.
```

Expected result: correct phone action with no calls or messages sent.

## Test Group 6: Failure Recovery

### 6.1 Provider fallback

Temporarily disconnect internet, then ask:

```text
Leha what time is it?
```

Expected result: local command still works.

Reconnect internet, then ask a general question:

```text
Leha explain machine learning in one sentence.
```

Expected result: Leha returns to cloud answers without manually restarting.

### 6.2 Microphone recovery observation

Leave Leha running for at least five minutes without speaking.

Expected result: heartbeat lines continue in `logs/leha-supervisor.out.log`.

Then speak:

```text
Leha health.
```

Expected result: one response. If no response arrives, preserve the latest log
lines before changing anything.

## Manual Pass Criteria

The current system is ready to move to the next phase only when all are true:

- no random spoken response in 30 minutes of normal room audio
- no duplicate or delayed stale voice in 20 consecutive commands
- at least 18 of 20 short addressed commands are transcribed correctly
- all safe local skills above give the expected result
- listener heartbeat continues and the listener recovers after a provider error
- logs contain no repeated crash loop

## What Still Needs Improvement For Siri/Alexa-Level Leha

### 1. Dedicated wake word: highest priority

Current transcript matching is a temporary solution. Build and evaluate the
private `Leha` wake model with positive, negative, and held-out recordings.

Target:

- at least 95% intended wake detection
- fewer than one false wake per hour of normal audio
- wake detection before cloud transcription

### 2. Acoustic echo cancellation

Without AEC, speaker audio can enter the microphone. This prevents reliable
interruptions while Leha speaks or music plays.

Target:

- `Leha stop` interrupts speech/music in under one second
- no self-trigger from Leha's own voice

### 3. Faster end-to-end response

An instant full intelligent answer cannot be guaranteed because speech capture,
network STT, cloud thinking, and neural TTS each take time. The experience can
still feel fast by using local commands, streaming speech, provider health
checks, and short answers.

Targets:

- local command first audio under 1.5 seconds after speech ends
- normal cloud answer first audio under 3 seconds on healthy internet
- provider failure moves to the next provider without freezing the mic

### 4. Provider reliability

Cloudflare, Groq, OpenAI, and Ollama need circuit breakers and measured
fallback tests. Cloudflare should be enabled only with a new restricted token.

### 5. One speech manager everywhere

Native listener, scheduler, browser client, Android client, and any future
integration must route speech through one controlled queue per device. The
system must cancel stale replies before they can play.

### 6. Safer, clearer device control

Improve window/app targeting, confirmation previews, audit logs, and undo for
reversible settings. Keep high-risk actions confirmation-gated forever.

### 7. Secure mobile companion

Android needs pairing approval, encrypted credentials, HTTPS/private tunnel,
reconnect handling, visible states, and strict remote capability limits.

### 8. Better Google and productivity workflows

Finish confirmed Calendar creation, email drafting/sending, Drive content
reading, contacts, and Maps travel time with quota limits.

### 9. Smart-home integration

Use Home Assistant as the central integration for lights, AC, TV, sensors, and
scenes. Add routines only after the voice core is stable.

### 10. Clone voice later

The current female Edge neural voice is the stable live voice. A realistic
clone needs clean consented recordings and an always-warm GPU service. Do not
replace the working live voice until clone latency, clarity, and cancellation
pass the same tests above.

## Do Not Change During This Test Cycle

- Do not enable `CUSTOM_WAKE_ENABLED`.
- Do not enable barge-in.
- Do not enable clone voice.
- Do not change STT provider, microphone index, thresholds, or brain order.
- Do not add new skills while collecting test results.

Run this guide first, keep the logs, and use the measured failing test as the
next implementation task.
