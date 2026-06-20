"""Always-listening wake-word detector built on openwakeword.

One continuous mic stream feeds a queue. The main loop pulls 80 ms frames,
scores them, and when 'Hey Jarvis' crosses the threshold it captures the
following command from the same stream. No blocking work in the callback.
"""
import queue
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model
from . import config


def _resolve_device(spec):
    """Resolve MIC_DEVICE: int/None passthrough; string -> matching input
    device index, preferring the MME host API (does sample-rate conversion)."""
    if spec is None or isinstance(spec, int):
        return spec
    hostapis = sd.query_hostapis()
    mme = next((i for i, h in enumerate(hostapis) if h["name"] == "MME"), None)
    matches = [(i, d) for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0 and spec.lower() in d["name"].lower()]
    if not matches:
        print(f"[wake] no input device matches '{spec}', using default")
        return None
    for i, d in matches:
        if d["hostapi"] == mme:
            return i
    return matches[0][0]


class WakeListener:
    def __init__(self):
        try:
            openwakeword.utils.download_models()
        except Exception as e:
            print(f"[wake] model download skipped: {e}")
        print("[wake] loading wake-word model ...")
        self.model = Model(wakeword_models=config.WAKE_MODELS)
        self.q: queue.Queue = queue.Queue()
        self.stream = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[wake] mic status: {status}")
        frame = indata.copy()
        if config.INPUT_GAIN and config.INPUT_GAIN != 1.0:
            frame = np.clip(frame.astype(np.float32) * config.INPUT_GAIN,
                            -32768, 32767).astype(np.int16)
        self.q.put(frame)

    def start(self):
        device = _resolve_device(config.MIC_DEVICE)
        print(f"[wake] mic device -> {device}")
        self.stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            blocksize=config.CHUNK,
            dtype="int16",
            device=device,
            callback=self._callback,
        )
        self.stream.start()

    def _flush(self):
        with self.q.mutex:
            self.q.queue.clear()

    def wait_for_wake(self):
        """Block until the wake word is heard; return (model_name, score)."""
        self.model.reset()
        while True:
            frame = self.q.get().flatten()
            preds = self.model.predict(frame)
            for name, score in preds.items():
                if score > config.WAKE_THRESHOLD:
                    self._flush()
                    return name, float(score)

    def capture_command(self, seconds: int) -> np.ndarray:
        """Collect `seconds` of audio from the live stream as int16."""
        self._flush()  # drop wake tail + any TTS echo
        needed = int(seconds * config.SAMPLE_RATE)
        collected, count = [], 0
        while count < needed:
            frame = self.q.get().flatten()
            collected.append(frame)
            count += len(frame)
        return np.concatenate(collected)[:needed].astype(np.int16)

    def capture_command_vad(self, max_seconds, silence_ms, silence_rms):
        """Record until the speaker goes quiet (voice-activity detection)."""
        self._flush()
        chunk_ms = 1000.0 * config.CHUNK / config.SAMPLE_RATE
        silence_needed = max(1, int(silence_ms / chunk_ms))
        max_chunks = int(max_seconds * 1000 / chunk_ms)
        frames, started, silent = [], False, 0
        for _ in range(max_chunks):
            frame = self.q.get().flatten()
            frames.append(frame)
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            if rms > silence_rms:
                started, silent = True, 0
            elif started:
                silent += 1
                if silent >= silence_needed:
                    break
        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(frames).astype(np.int16)

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
