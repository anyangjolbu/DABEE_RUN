import json
from pathlib import Path
p = Path("data/settings.json")
s = json.loads(p.read_text(encoding="utf-8"))
changed = False
if "collection_lookback_days" not in s:
    s["collection_lookback_days"] = 0  # 0=무제한
    changed = True
if "naver_display_count" not in s:
    s["naver_display_count"] = 20
    changed = True
if changed:
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ settings.json 보정 완료")
else:
    print("⏭️ settings.json 이미 OK")
print(f"  naver_display_count: {s['naver_display_count']}")
print(f"  collection_lookback_days: {s['collection_lookback_days']}")
