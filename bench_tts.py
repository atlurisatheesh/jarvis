"""Benchmark new sounddevice TTS vs old PowerShell path."""
import asyncio
import time
import miniaudio
import sounddevice as sd
import numpy as np


async def _collect(text: str) -> bytes:
    import edge_tts
    chunks = []
    communicate = edge_tts.Communicate(text, "en-US-AvaMultilingualNeural", rate="-3%", pitch="+0Hz")
    async for item in communicate.stream():
        type_ = item["type"]
        if type_ == "audio":
            chunks.append(item["data"])
    return b"".join(chunks)


def bench():
    text = "Yes Sir, I am ready and listening."
    print(f"Text: '{text}'")

    t0 = time.perf_counter()
    mp3_data = asyncio.run(_collect(text))
    t1 = time.perf_counter()

    decoded = miniaudio.decode(mp3_data)
    t2 = time.perf_counter()

    samples_i16 = np.frombuffer(bytes(decoded.samples), dtype=np.int16)
    if decoded.nchannels == 2:
        samples_i16 = samples_i16.reshape(-1, 2).mean(axis=1).astype(np.int16)
    samples_f32 = samples_i16.astype(np.float32) / 32768.0

    print(f"edge-tts stream:   {(t1-t0)*1000:.0f}ms")
    print(f"miniaudio decode:  {(t2-t1)*1000:.0f}ms")
    print(f"total to audio ready: {(t2-t0)*1000:.0f}ms  (was ~700ms with PS overhead)")
    print(f"audio duration:    {decoded.num_frames/decoded.sample_rate*1000:.0f}ms  ({decoded.sample_rate}Hz, {decoded.nchannels}ch)")

    print("Playing via sounddevice (no subprocess)...")
    t3 = time.perf_counter()
    sd.play(samples_f32, samplerate=decoded.sample_rate)
    sd.wait()
    t4 = time.perf_counter()
    print(f"Playback done in {(t4-t3)*1000:.0f}ms")


if __name__ == "__main__":
    bench()
