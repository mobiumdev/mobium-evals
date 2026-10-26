"""Score a judge's verdicts against claims.json's expected answers.

    python3 claims/score.py claims/results/<run>.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
claims = {c["id"]: c for c in json.loads((HERE / "claims.json").read_text())["claims"]}
run = json.loads(Path(sys.argv[1]).read_text())
got = run["verdicts"]
missing = sorted(set(claims) - set(got))
grid = Counter((claims[i]["expected"], got[i]["status"]) for i in claims if i in got)
right = sum(n for (e, g), n in grid.items() if e == g)
print(f"{run['judge']}\n")
print(f"{right} of {len(claims)} right" + (f"; no verdict for {', '.join(missing)}" if missing else ""))
kinds = ("passed", "failed", "inconclusive")
print("\nexpected \\ judged  " + "  ".join(f"{k:>12}" for k in kinds))
for e in kinds:
    print(f"{e:>18}  " + "  ".join(f"{grid[(e, g)]:>12}" for g in kinds))
wrong = [i for i in claims if i in got and got[i]["status"] != claims[i]["expected"]]
for i in wrong:
    print(f"\n{i}: expected {claims[i]['expected']}, judged {got[i]['status']}: {claims[i]['claim']}")
sys.exit(0 if not wrong and not missing else 1)
