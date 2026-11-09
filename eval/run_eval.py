"""SafePay Guardian risk-engine evaluation.

Runs the 16 labelled cases in eval/cases.json and compares three ways of deciding:
  rules only  - the deterministic rules (what the app does when the AI is unavailable)
  AI only     - the AI's recommended action mapped directly (proceed/warn/guardian_review = low/medium/high)
  hybrid      - the shipped engine: rules floor + grounded AI + aggregation

One AI call per case feeds all three columns. AI replies are cached in eval/cache/ (with the latency of the
original call), so the evaluation can be re-run offline and inside free-tier limits.

Usage (from the repo root):
  .venv/Scripts/python eval/run_eval.py              # live AI for uncached cases, cache the replies
  .venv/Scripts/python eval/run_eval.py --cached     # offline: only cached replies, no API key needed
  .venv/Scripts/python eval/run_eval.py --rules-only # no AI at all
  .venv/Scripts/python eval/run_eval.py --repeat 3   # also measure run-to-run consistency (2 extra live passes)

Writes eval/results.md and eval/results.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.risk import ai as ai_mod  # noqa: E402
from app.risk import config as C  # noqa: E402
from app.risk.engine import HybridEngine  # noqa: E402
from app.risk.types import PaymentContext  # noqa: E402

EVAL_DIR = ROOT / "eval"
CACHE_DIR = EVAL_DIR / "cache"
COLUMNS = ("rules", "ai", "hybrid")
COLUMN_NAMES = {"rules": "Rules only", "ai": "AI only", "hybrid": "Hybrid"}
GROUP_NAMES = {"legit": "Legit", "scam": "Scam", "ambiguous": "Ambiguous", "adversarial": "Adversarial"}
RETRYABLE = {"rate_limited", "timeout", "network", "http"}


def cents(dollars: float | str) -> int:
    return int(round(float(dollars) * 100))


def build_context(case: dict, default_history: list[float]) -> PaymentContext:
    p, payee = case["payment"], case["payee"]
    history = [cents(d) for d in default_history] + [cents(d) for d in payee.get("past_amounts_dollars", [])]
    return PaymentContext(
        amount_cents=cents(p["amount"]), currency="USD", payee_name=p["payee_name"],
        payee_is_new=payee["status"] == "new", payee_trusted=payee["status"] == "trusted",
        note=p["note"], message_text=p["message_text"], history_amounts_cents=history,
        payee_history_count=payee.get("past_payments", 0),
    )


def is_cited(result, token: str) -> bool:
    kind, value = token.split(":", 1)
    if kind == "type":
        return any(i["type"] == value for i in result.indicators)
    if kind == "family":
        return (result.ai or {}).get("category") == value or any(p["category"] == value for p in result.patterns)
    raise ValueError(f"unknown citation token {token}")


def assess_with_retry(engine: HybridEngine, ctx: PaymentContext, case_id: str, live: bool):
    for attempt in range(4):
        result = engine.assess(ctx)
        kind = result.components.get("ai_error_kind")
        if live and kind in RETRYABLE and attempt < 3:
            wait = 20 * (attempt + 1)
            print(f"   {case_id}: AI {kind}, retrying in {wait}s")
            time.sleep(wait)
            continue
        if live and kind in RETRYABLE:
            # Do not write a results file where the AI silently fell back to rules: stop instead.
            sys.exit(f"Stopped at {case_id}: AI {kind} after retries ({result.ai_error}). "
                     "Replies so far are cached; re-run later and they will be reused.")
        return result
    return result  # pragma: no cover


def run_pass(engine: HybridEngine, cases: list[dict], default_history: list[float], *, live: bool,
             sleep: float, label: str) -> list[dict]:
    rows = []
    provider = engine.provider
    for case in cases:
        ctx = build_context(case, default_history)
        result = assess_with_retry(engine, ctx, case["id"], live)
        comp = result.components
        cached = bool(getattr(provider, "last_was_cached", False))
        latency = getattr(provider, "last_latency_ms", None) if comp["ai_ok"] else None
        if latency is None and comp["ai_ok"]:
            latency = result.latency_ms
        expected = case["expect"]["levels"]
        levels = {"rules": comp["rules_level"], "ai": comp["ai_only_level"], "hybrid": result.level}
        cites = case["expect"]["cite"]
        missing = [t for t in cites if not is_cited(result, t)]
        for ind in result.indicators:  # displayed AI evidence must be grounded, by construction
            if ind["source"] == "ai":
                assert ind["spans"], f"{case['id']}: ungrounded AI evidence was kept: {ind}"
        rows.append({
            "id": case["id"], "group": case["group"], "scenario": case["scenario"], "expected": expected,
            "levels": levels, "ok": {c: levels[c] in expected for c in COLUMNS},
            "cite_required": cites, "cite_missing": missing,
            "score": result.score, "rules_score": comp["rules_score"], "mode": result.mode,
            "ai_ok": comp["ai_ok"], "ai_error_kind": comp["ai_error_kind"],
            "ai_valid_first_try": comp["ai_valid_first_try"], "ai_cached": cached, "latency_ms": latency,
            "category": (result.ai or {}).get("category"), "confidence": (result.ai or {}).get("confidence"),
            "ai_kept": [{"type": i["type"], "evidence": i["evidence"]} for i in result.indicators if i["source"] == "ai"],
            "dropped": result.dropped_evidence,
            "rule_types": [i["type"] for i in result.indicators if i["source"] == "rule"],
            "patterns": [p["id"] for p in result.patterns],
            "summary": result.summary,
        })
        flag = "ok " if rows[-1]["ok"]["hybrid"] else "MISS"
        src = "cache" if cached else ("live" if comp["ai_ok"] else (comp["ai_error_kind"] or "no-ai"))
        print(f"{label} {flag} {case['id']:3s} rules={levels['rules']:6s} ai={str(levels['ai']):6s} "
              f"hybrid={levels['hybrid']:6s} [{src}]")
        if live and comp["ai_ok"] and not cached and sleep:
            time.sleep(sleep)  # stay inside free-tier requests-per-minute
    return rows


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def metrics(rows: list[dict]) -> dict:
    scams = [r for r in rows if r["group"] in ("scam", "adversarial")]
    legit = [r for r in rows if r["group"] == "legit"]
    m: dict = {"columns": {}}
    for c in COLUMNS:
        m["columns"][c] = {
            "scam_catch": (sum(r["levels"][c] == "high" for r in scams), len(scams)),
            "false_hold": (sum(r["levels"][c] == "high" for r in legit), len(legit)),
            "accuracy": (sum(r["ok"][c] for r in rows), len(rows)),
            "misses": [r["id"] for r in rows if not r["ok"][c]],
        }
    ai_rows = [r for r in rows if r["ai_ok"] or r["ai_error_kind"] not in (None, "not_configured")]
    replies = [r for r in ai_rows if r["ai_ok"] or r["ai_error_kind"] in ("invalid_json", "schema")]
    kept = sum(len(r["ai_kept"]) for r in rows)
    dropped = sum(len(r["dropped"]) for r in rows)
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    cite_rows = [r for r in rows if r["cite_required"]]
    d2 = next((r for r in rows if r["id"] == "D2"), None)
    m.update({
        "json_valid": (sum(r["ai_valid_first_try"] for r in replies), len(replies)),
        "ai_failures": [f"{r['id']}:{r['ai_error_kind']}" for r in ai_rows if not r["ai_ok"]],
        "evidence_kept": kept, "evidence_dropped": dropped,
        "latency_median_ms": int(statistics.median(latencies)) if latencies else None,
        "latency_max_ms": max(latencies) if latencies else None,
        "citations": (sum(not r["cite_missing"] for r in cite_rows), len(cite_rows)),
        "injection_resistant": bool(d2 and d2["levels"]["hybrid"] == "high"),
        "cached": sum(r["ai_cached"] for r in rows),
    })
    return m


def consistency(passes: list[list[dict]]) -> dict | None:
    if len(passes) < 2:
        return None
    ids = [r["id"] for r in passes[0]]
    out = {}
    for c in ("ai", "hybrid"):
        stable = [i for i, case_id in enumerate(ids) if len({p[i]["levels"][c] for p in passes}) == 1]
        out[c] = (len(stable), len(ids), [ids[i] for i in range(len(ids)) if i not in stable])
    return out


def level_cell(level: str | None, ok: bool) -> str:
    return f"{(level or 'n/a').capitalize()}{'' if ok else ' ✗'}"


def report(rows: list[dict], m: dict, cons: dict | None, meta: dict) -> str:
    cols = m["columns"]
    lines = [
        "# SafePay Guardian: risk-engine evaluation",
        "",
        f"Generated {meta['generated']} by `python eval/run_eval.py`. Model `{meta['model']}`, "
        f"prompt `{meta['prompt_version']}`, config `{meta['config_version']}`. "
        f"AI replies: {meta['live']} live, {m['cached']} from cache.",
        "",
        "16 cases written for this project (4 legitimate, 6 scams, 3 ambiguous, 3 adversarial). "
        "It is a small, self-written set: the numbers show the design works on the cases we chose, "
        "not a measured real-world fraud rate.",
        "",
        "## Rules only vs AI only vs hybrid",
        "",
        "| Metric | Target | Rules only | AI only | Hybrid |",
        "|---|---|---|---|---|",
        f"| Scam catch rate (scam + adversarial cases reaching High) | 100% | "
        + " | ".join(pct(*cols[c]["scam_catch"]) for c in COLUMNS) + " |",
        "| False hold rate (legit cases reaching High) | 0 of 4 | "
        + " | ".join(f"{cols[c]['false_hold'][0]} of {cols[c]['false_hold'][1]}" for c in COLUMNS) + " |",
        "| Level accuracy (in the labelled or allowed level) | report | "
        + " | ".join(pct(*cols[c]["accuracy"]) for c in COLUMNS) + " |",
        "| Cases outside the allowed level | | "
        + " | ".join(", ".join(cols[c]["misses"]) or "none" for c in COLUMNS) + " |",
        "",
        "## AI quality",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| JSON validity (replies that parse and match the schema on the first try) | {pct(*m['json_valid'])} |",
        f"| AI call failures (fell back to rules only) | {', '.join(m['ai_failures']) or 'none'} |",
        f"| Evidence grounding (shown AI evidence found in the input) | 100% by construction "
        f"({m['evidence_kept']} quotes kept, {m['evidence_dropped']} proposed quotes dropped) |",
        f"| Required evidence cited (hybrid) | {pct(*m['citations'])} |",
        f"| Injection resistance (D2 stays High) | {'Pass' if m['injection_resistant'] else 'FAIL'} |",
        f"| AI latency, median / slowest | "
        + (f"{m['latency_median_ms']} ms / {m['latency_max_ms']} ms" if m["latency_median_ms"] is not None else "n/a")
        + " |",
    ]
    if cons:
        lines.append(
            f"| Run-to-run consistency ({meta['repeat']} runs) | AI only identical in {cons['ai'][0]}/{cons['ai'][1]} "
            f"cases{(' (varied: ' + ', '.join(cons['ai'][2]) + ')') if cons['ai'][2] else ''}; hybrid identical in "
            f"{cons['hybrid'][0]}/{cons['hybrid'][1]}{(' (varied: ' + ', '.join(cons['hybrid'][2]) + ')') if cons['hybrid'][2] else ''} |")
    lines += [
        "",
        "## Cases",
        "",
        "✗ marks a level outside the allowed set.",
        "",
        "| ID | Type | Scenario | Allowed | Rules only | AI only | Hybrid | Required evidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cites = "none required" if not r["cite_required"] else (
            "all cited" if not r["cite_missing"] else "missing " + ", ".join(r["cite_missing"]))
        lines.append(
            f"| {r['id']} | {GROUP_NAMES[r['group']]} | {r['scenario']} | "
            f"{' or '.join(l.capitalize() for l in r['expected'])} | "
            + " | ".join(level_cell(r["levels"][c], r["ok"][c]) for c in COLUMNS)
            + f" | {cites} |")
    lines += ["", "## Evidence per case (hybrid)", ""]
    for r in rows:
        ai_ev = "; ".join(f"{k['type']}: \"{k['evidence']}\"" for k in r["ai_kept"]) or "none"
        drop = "; ".join(f"{d['type']}: \"{d['evidence']}\" ({d['reason']})" for d in r["dropped"]) or "none"
        lines.append(f"- **{r['id']}** score {r['score']} (rules {r['rules_score']}). Rules: "
                     f"{', '.join(r['rule_types']) or 'none'}. AI ({r['category'] or 'n/a'}, {r['confidence'] or 'n/a'} "
                     f"confidence): {ai_ev}. Dropped: {drop}. Patterns: {', '.join(r['patterns']) or 'none'}.")
    lines += [
        "",
        "## How to read this",
        "",
        "- The risk level is a decision aid, not a validated fraud probability. Scores are heuristic sums of weights.",
        "- Thresholds and weights live in `backend/app/risk/config.py`. They were tuned once on these cases and then "
        "frozen; see `docs/BUILD_PLAN.md`.",
        "- AI only maps the model's recommended action straight to a level. Hybrid only lets the AI raise a level, and "
        "only with evidence that literally appears in the message or payment.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cached", action="store_true", help="offline: use only cached AI replies")
    parser.add_argument("--rules-only", action="store_true", help="run without any AI")
    parser.add_argument("--repeat", type=int, default=1, help="total passes; extra passes bypass the cache")
    parser.add_argument("--sleep", type=float, default=7.0, help="seconds between live AI calls")
    parser.add_argument("--timeout", type=float, default=None,
                        help="AI timeout in seconds for this run (default: AI_TIMEOUT_SECONDS, 8s in the app)")
    args = parser.parse_args()

    data = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
    cases, history = data["cases"], data["default_history_dollars"]
    settings = get_settings()
    if args.timeout:
        settings = settings.model_copy(update={"ai_timeout_seconds": args.timeout})

    if args.rules_only:
        engine, inner = HybridEngine(None), None
    else:
        if args.cached:
            inner = None
            provider = ai_mod.CachingProvider(ai_mod.ReplayOnly(settings.gemini_model), CACHE_DIR, offline=True)
        else:
            if not settings.ai_configured:
                sys.exit("No AI configured. Set AI_PROVIDER=gemini and GEMINI_API_KEY in .env, or use --cached.")
            inner = ai_mod.GeminiProvider(settings)
            provider = ai_mod.CachingProvider(inner, CACHE_DIR)
        engine = HybridEngine(provider)

    live = not args.cached and not args.rules_only
    rows = run_pass(engine, cases, history, live=live, sleep=args.sleep, label="pass 1")
    passes = [rows]
    for n in range(2, args.repeat + 1):
        if inner is None:
            sys.exit("--repeat needs live AI (not --cached or --rules-only)")
        passes.append(run_pass(HybridEngine(inner), cases, history, live=True, sleep=args.sleep, label=f"pass {n}"))

    m = metrics(rows)
    cons = consistency(passes)
    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model": "none (rules only)" if args.rules_only else settings.gemini_model,
        "prompt_version": ai_mod.PROMPT_VERSION, "config_version": C.CONFIG_VERSION,
        "live": sum(1 for r in rows if r["ai_ok"] and not r["ai_cached"]), "repeat": args.repeat,
        "ai_timeout_seconds": settings.ai_timeout_seconds,
    }
    md = report(rows, m, cons, meta)
    (EVAL_DIR / "results.md").write_text(md, encoding="utf-8")
    (EVAL_DIR / "results.json").write_text(json.dumps(
        {"meta": meta, "metrics": m, "consistency": cons, "rows": rows,
         "extra_passes": [[{"id": r["id"], "levels": r["levels"]} for r in p] for p in passes[1:]]},
        indent=2, default=list), encoding="utf-8")
    print()
    print(md.split("## Evidence per case")[0])
    print(f"Saved {EVAL_DIR / 'results.md'}")


if __name__ == "__main__":
    main()
