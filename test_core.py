from jarvis_ai.ears import Ears
from jarvis_ai.audio import record_command

e = Ears()
print("SPEAK NOW — full sentence...", flush=True)
a = record_command()
print("captured samples:", len(a), flush=True)
print("HEARD:", e.transcribe_int16(a), flush=True)
