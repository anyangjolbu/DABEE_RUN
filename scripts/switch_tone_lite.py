import json, pathlib
p = pathlib.Path("data/settings.json")
s = json.loads(p.read_text(encoding="utf-8"))
old = s.get("gpt_model_tone")
s["gpt_model_tone"] = "gemini-flash-lite-latest"
p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✏️  gpt_model_tone: {old} → gemini-flash-lite-latest")
