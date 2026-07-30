"""M0 spike: does an Anthropic-compatible gateway support native tool_use?"""
import os, sys, pathlib

# load env from the original project's .env (covers ANTHROPIC_* + SAAS_LLM_MODEL)
ENV = pathlib.Path("/mnt/workspace/workgroup5/zhanfeng/SuperAcademicAISearch/.env")
for line in ENV.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip())

import anthropic

base_url = os.environ.get("ANTHROPIC_BASE_URL")
auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
api_key = os.environ.get("ANTHROPIC_API_KEY")
model = os.environ.get("SAAS_LLM_MODEL") or "claude-sonnet-4-6"
print(f"base_url={base_url!r}  model={model!r}  auth_token={'set' if auth_token else 'none'}  api_key={'set' if api_key else 'none'}")

kwargs = {}
if base_url: kwargs["base_url"] = base_url
if auth_token: kwargs["auth_token"] = auth_token
if api_key: kwargs["api_key"] = api_key
client = anthropic.Anthropic(**kwargs)

tools = [{
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    },
}]

resp = client.messages.create(
    model=model,
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "What's the weather in Tokyo right now? Use the tool."}],
)

print("stop_reason:", resp.stop_reason)
tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
texts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
print("block types:", [getattr(b, "type", None) for b in resp.content])
if tool_uses:
    tu = tool_uses[0]
    print("✅ NATIVE tool_use SUPPORTED")
    print("   tool name:", tu.name, " input:", tu.input)
else:
    print("❌ no tool_use block returned")
    print("   text:", (texts[0] if texts else "")[:500])
