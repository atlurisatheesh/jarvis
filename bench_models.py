"""Benchmark brain models: latency + tool-call correctness on this CPU."""
import time

from jarvis_ai import config, skills
import ollama

QUESTION = "What is 18 percent of 2450?"
MODELS = ["qwen2.5:3b", "qwen2.5:7b"]
client = ollama.Client(host=config.OLLAMA_HOST)


def run(model):
    msgs = [{"role": "system", "content": config.SYSTEM_PROMPT},
            {"role": "user", "content": QUESTION}]
    t0 = time.time()
    tool_used = None
    for _ in range(4):
        r = client.chat(model=model, messages=msgs, tools=skills.TOOLS,
                        options={"num_predict": 200})
        m = r["message"]
        msgs.append(m)
        tc = m.get("tool_calls")
        if not tc:
            return time.time() - t0, tool_used, (m.get("content") or "").strip()
        for c in tc:
            tool_used = c["function"]["name"]
            res = skills.run_tool(tool_used, c["function"].get("arguments", {}) or {})
            msgs.append({"role": "tool", "name": tool_used, "content": res})
    return time.time() - t0, tool_used, "(loop)"


for model in MODELS:
    try:
        secs, tool, reply = run(model)
        print(f"\n=== {model} ===")
        print(f"  time: {secs:.1f}s   tool: {tool}")
        print(f"  reply: {reply}")
    except Exception as e:
        print(f"\n=== {model} === ERROR: {e}")
