import os, pathlib, anthropic
ENV = pathlib.Path("/mnt/workspace/workgroup5/zhanfeng/SuperAcademicAISearch/.env")
for line in ENV.read_text().splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
client = anthropic.Anthropic(base_url=os.environ["ANTHROPIC_BASE_URL"], auth_token=os.environ["ANTHROPIC_AUTH_TOKEN"])
tools=[{"name":"get_weather","description":"Get current weather for a city.",
        "input_schema":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}]
for m in ["qwen3.7-max","claude-sonnet-4-6","claude-opus-4-8"]:
    try:
        r=client.messages.create(model=m,max_tokens=512,tools=tools,
            messages=[{"role":"user","content":"What's the weather in Tokyo? Use the tool."}])
        types=[getattr(b,"type",None) for b in r.content]
        tu=[b for b in r.content if getattr(b,"type",None)=="tool_use"]
        if tu:
            print(f"✅ {m:20s} tool_use OK  stop={r.stop_reason}  name={tu[0].name} input={tu[0].input}")
        else:
            txt="".join(b.text for b in r.content if getattr(b,'type',None)=='text')[:80]
            print(f"⚠️  {m:20s} NO tool_use  stop={r.stop_reason}  types={types}  text={txt!r}")
    except Exception as e:
        print(f"❌ {m:20s} {str(e)[:90]}")
