"""Probe: does DashScope qwen3.7-max (OpenAI-compatible) support tool calling? Is quota OK?"""
import re, pathlib
from openai import OpenAI

# extract DASHSCOPE_API_KEY + model even from commented lines in .env
env = pathlib.Path("/mnt/workspace/workgroup5/zhanfeng/SuperAcademicAISearch/.env").read_text()
key = re.search(r"DASHSCOPE_API_KEY=(\S+)", env).group(1).strip()
base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen3.7-max"
print("base:", base, "model:", model, "key:", key[:6] + "****")

client = OpenAI(api_key=key, base_url=base)
tools = [{"type": "function", "function": {
    "name": "get_weather", "description": "Get current weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
r = client.chat.completions.create(
    model=model, max_tokens=256, tools=tools, tool_choice="auto",
    messages=[{"role": "user", "content": "What's the weather in Tokyo? Use the tool."}])
msg = r.choices[0].message
tc = msg.tool_calls or []
if tc:
    print("✅ tool calling OK:", tc[0].function.name, tc[0].function.arguments)
else:
    print("⚠️ no tool_calls; content=", (msg.content or "")[:200])
print("usage:", r.usage)
