"""Probe which models this gateway token can access (text call)."""
import os, pathlib, anthropic
ENV = pathlib.Path("/mnt/workspace/workgroup5/zhanfeng/SuperAcademicAISearch/.env")
for line in ENV.read_text().splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
client = anthropic.Anthropic(base_url=os.environ["ANTHROPIC_BASE_URL"], auth_token=os.environ["ANTHROPIC_AUTH_TOKEN"])
CANDIDATES = [
    "qwen3-max","qwen3.7-max","Qwen3-Max","qwen-max",
    "claude-sonnet-4-6","claude-sonnet-4-5","claude-3-7-sonnet","claude-3-5-sonnet-20241022",
    "claude-opus-4-8","claude-haiku-4-5",
]
for m in CANDIDATES:
    try:
        r=client.messages.create(model=m,max_tokens=32,messages=[{"role":"user","content":"say OK"}])
        txt="".join(b.text for b in r.content if getattr(b,"type",None)=="text")[:40]
        print(f"✅ {m:32s} -> {txt!r}")
    except Exception as e:
        msg=str(e)
        short = msg.split("message")[1][:70] if "message" in msg else msg[:70]
        print(f"❌ {m:32s} -> {short}")
