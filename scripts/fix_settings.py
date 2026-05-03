import json, pathlib
p = pathlib.Path("data/settings.json")
s = json.loads(p.read_text(encoding="utf-8"))
print("=== 현재 settings.json 키 ===")
for k in sorted(s.keys()):
    v = s[k]
    if isinstance(v, (str, int, float, bool)) or v is None:
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: <{type(v).__name__}>")

# 모델 키 보정
changed = False
if not s.get("gpt_model_tier1"):
    s["gpt_model_tier1"] = "gemini-flash-lite-latest"
    changed = True
    print("✏️  gpt_model_tier1 → gemini-flash-lite-latest 추가")
if not s.get("gpt_model_tier2"):
    s["gpt_model_tier2"] = "gemini-flash-lite-latest"
    changed = True
    print("✏️  gpt_model_tier2 → gemini-flash-lite-latest 추가")

if changed:
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ settings.json 저장 완료")
else:
    print("✅ 모델 키 이미 정상")
