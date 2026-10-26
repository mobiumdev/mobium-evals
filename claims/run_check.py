"""Run `mobium check` over every claim with one model, and save the verdicts
in results/ for score.py.

    python3 claims/run_check.py openai:qwen2.5:14b [--mobium PATH]

Each claim is its own check: a fresh model context, the claim, and its
recording; nothing else. A check that errors is kept as "error".
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--only", help="comma-separated claim ids, merged into today's results for the model")
    ap.add_argument("--mobium", default=str(Path.home() / "mobium-public/bin/mobium"))
    a = ap.parse_args()
    claims = json.loads((HERE / "claims.json").read_text())["claims"]
    date = datetime.date.today().isoformat()
    name = a.model.replace(":", "-").replace("/", "-")
    path = HERE / "results" / f"{date}-{name}.json"
    verdicts = {}
    if a.only:
        if path.exists():
            verdicts = json.loads(path.read_text())["verdicts"]
        claims = [c for c in claims if c["id"] in a.only.split(",")]
    for c in claims:
        t0 = time.time()
        p = subprocess.run([a.mobium, "check", c["claim"], "-i", str(HERE / c["record"]), "--model", a.model, "--json"],
                           capture_output=True, text=True, timeout=1200)
        secs = round(time.time() - t0, 1)
        try:
            v = json.loads(p.stdout)
            verdicts[c["id"]] = {"status": v["status"], "summary": v.get("summary", ""), "steps": v.get("steps"),
                                 "evidence": [e["summary"] for e in v.get("evidence") or []], "seconds": secs}
        except (json.JSONDecodeError, KeyError):
            verdicts[c["id"]] = {"status": "error", "error": (p.stderr or p.stdout).strip()[:500], "seconds": secs}
        print(f"{c['id']} expected {c['expected']:<12} judged {verdicts[c['id']]['status']:<12} {secs}s", flush=True)
    out = {"judge": f"mobium check --model {a.model} (each claim its own check)", "date": date, "verdicts": verdicts}
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"saved {path.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
