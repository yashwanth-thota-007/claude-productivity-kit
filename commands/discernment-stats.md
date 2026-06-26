# Discernment Stats

Show scoring trends from the discernment log at `~/.claude/discernment-log.jsonl`.

## Instructions

Run the following Python inline to read and render the stats, then present the results clearly.

```python
import json, pathlib, statistics
from collections import defaultdict

log = pathlib.Path.home() / ".claude" / "discernment-log.jsonl"
if not log.exists():
    print("No discernment log found at ~/.claude/discernment-log.jsonl")
    exit()

entries = []
for line in log.read_text().strip().splitlines():
    try:
        entries.append(json.loads(line))
    except Exception:
        continue

if not entries:
    print("Log exists but has no entries yet.")
    exit()

composites   = [e["composite"] for e in entries]
product_scores  = [e["product"]["score"] for e in entries if "product" in e]
process_scores  = [e["process"]["score"] for e in entries if "process" in e]
perf_scores     = [e["performance"]["score"] for e in entries if "performance" in e]

def avg(lst): return round(sum(lst)/len(lst), 2) if lst else 0
def trend(lst):
    if len(lst) < 2: return "→ (not enough data)"
    delta = lst[-1] - lst[0]
    if delta > 0.5: return f"↑ +{delta:.1f}"
    if delta < -0.5: return f"↓ {delta:.1f}"
    return "→ stable"

THRESHOLD = 6.5
retries = sum(1 for c in composites if c < THRESHOLD)

# session breakdown — last 10
recent = entries[-10:]

print(f"=== Discernment Score Trends ===")
print(f"Total scored responses : {len(entries)}")
print(f"Retries triggered      : {retries} ({round(retries/len(entries)*100)}%)")
print()
print(f"{'Dimension':<14} {'Avg':>6}  {'Min':>5}  {'Max':>5}  {'Trend':>12}")
print("-" * 48)
for label, scores in [("Composite", composites), ("Product", product_scores), ("Process", process_scores), ("Performance", perf_scores)]:
    if scores:
        print(f"{label:<14} {avg(scores):>6}  {min(scores):>5}  {max(scores):>5}  {trend(scores):>12}")
print()
print(f"=== Last {len(recent)} Responses ===")
print(f"{'#':<4} {'Composite':>9}  {'Product':>7}  {'Process':>7}  {'Perf':>5}  {'Retry?':>7}")
print("-" * 48)
for i, e in enumerate(recent, 1):
    c  = e.get("composite", "?")
    pr = e.get("product",  {}).get("score", "?")
    pc = e.get("process",  {}).get("score", "?")
    pf = e.get("performance", {}).get("score", "?")
    retry = "YES" if isinstance(c, float) and c < THRESHOLD else "-"
    print(f"{i:<4} {str(c):>9}  {str(pr):>7}  {str(pc):>7}  {str(pf):>5}  {retry:>7}")

# weakest dimension
dim_avgs = {
    "Product":     avg(product_scores),
    "Process":     avg(process_scores),
    "Performance": avg(perf_scores),
}
weakest = min(dim_avgs, key=dim_avgs.get)
print()
print(f"Weakest dimension: {weakest} (avg {dim_avgs[weakest]})")
print(f"Strongest dimension: {max(dim_avgs, key=dim_avgs.get)} (avg {max(dim_avgs.values())})")
```

Execute this Python code using the Bash tool and present the output as-is. Do not paraphrase or reformat the numbers. After the output, add one short paragraph interpreting what the trend means for the current session quality — mention which dimension needs the most attention and whether retries are being triggered frequently.
