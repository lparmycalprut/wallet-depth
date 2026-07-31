"""Debug RAKO scoring from real GMGN data."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gmgn_screener import screen, score_token

rows = screen()

# Find RAKO
rako = None
for r in rows:
    sym = (r.get("symbol") or "").lower()
    nm = (r.get("name") or "").lower()
    if "rako" in sym or "rako" in nm:
        rako = r
        break

if rako:
    print("=== RAKO raw data ===")
    for k, v in sorted(rako.items()):
        print(f"  {k}: {v}")
else:
    print("RAKO not found in trending. Top 20 tokens:")
    for r in rows[:20]:
        fit = r.get("fit", "?")
        sym = r.get("symbol", "?")
        chg = r.get("chg24", 0)
        t10 = r.get("t10_pct", 0)
        liq = r.get("liq_pct", 0)
        rug = r.get("rug", 0)
        hd = r.get("holders", 0)
        notes = r.get("notes", "")
        print(f"  {sym:>12} fit={fit:>3} chg24={chg:>+6.0f} "
              f"t10={t10:>5.1f} liq={liq:>5.1f} "
              f"rug={rug:.2f} hd={hd:>5} notes={notes}")

# Also save full output to file
with open("debug_rako_output.txt", "w") as f:
    for r in rows:
        f.write(json.dumps({k: v for k, v in r.items() if k != "ca"}, default=str) + "\n")
print(f"\nFull output saved to debug_rako_output.txt ({len(rows)} tokens)")