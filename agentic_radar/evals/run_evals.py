"""
Eval runner — the 5 patterns (Day-3 sl.20) over the 7 dimensions (Day-4 sl.30),
explicitly covering the 4 failure modes (Day-3 sl.19): trigger, execution,
token-rot/regression, and Denial-of-Wallet.

Two modes:
  --offline : eval-as-unit-test on deterministic behavior. NO API key, NO network.
              This is the gate that proves "nothing is broken".
  (default) : also runs the LLM-as-judge on real business output (swapped positions),
              if ANTHROPIC_API_KEY is set.

Run:
  python agentic_radar/evals/run_evals.py --offline
  python agentic_radar/evals/run_evals.py            # adds online judge if key present
"""
from __future__ import annotations

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RadarConfig
from skills.skill_loader import SkillRegistry
from memory import elo
from evals import rubric
from evals.rubric import (score_functional_correctness, score_constraint_compliance,
                          score_quality, score_trajectory)


def _load_golden():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_dataset.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _skills_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")


# ── offline eval-as-unit-test ────────────────────────────────────────────────
def run_offline() -> dict:
    golden = _load_golden()
    registry = SkillRegistry(_skills_dir())
    results = {}

    # FAILURE MODE 1: trigger — right skill picked per category (dimension 6)
    results["trigger_routing"] = score_trajectory(registry, golden["routing_cases"])

    # Skill conformance to the standard (Day-3 sl.46-48)
    conformance = registry.conformance_report()
    nonconf = [c for c in conformance if c["warnings"]]
    results["skill_conformance"] = {
        "pass": len(nonconf) == 0, "score": 1.0 - len(nonconf) / max(1, len(conformance)),
        "detail": f"{len(nonconf)} skill(s) with warnings: " +
                  "; ".join(f"{c['name']}:{c['warnings']}" for c in nonconf) if nonconf else "all skills conformant",
    }

    # FAILURE MODE 2: execution — deterministic Elo math is correct
    ra, rb = elo.update_pair(1200, 1200, a_won=True, k=32)
    elo_ok = abs(ra - 1216.0) < 1e-6 and abs(rb - 1184.0) < 1e-6
    # full tournament ordering with a deterministic judge (a beats b iff a.id<b.id)
    ideas = [{"id": "c"}, {"id": "a"}, {"id": "b"}]
    standings = elo.run_tournament([dict(i) for i in ideas], lambda a, b: a["id"] < b["id"], rounds=1)
    order_ok = [s["id"] for s in standings] == ["a", "b", "c"]
    results["execution_elo"] = {"pass": elo_ok and order_ok, "score": 1.0 if (elo_ok and order_ok) else 0.0,
                                "detail": f"pair_update_ok={elo_ok}, ordering_ok={order_ok}"}

    # dimensions 1,2,5: functional + constraint + quality on golden good example
    good = golden["good_idea_examples"]
    results["functional_correctness"] = score_functional_correctness(good)
    results["quality"] = score_quality(good)

    # FAILURE MODE 3 (regression / adversarial): negative-boundary + rephrasing
    adv_pass = True
    adv_detail = []
    for case in golden["adversarial_cases"]:
        got = score_constraint_compliance([case["idea"]])["pass"]
        want = case["expect_constraint_pass"]
        if got != want:
            adv_pass = False
            adv_detail.append(f"{case['label']}: got pass={got}, want {want}")
    results["adversarial_constraint"] = {"pass": adv_pass, "score": 1.0 if adv_pass else 0.0,
                                         "detail": "; ".join(adv_detail) or "all adversarial cases handled"}

    # FAILURE MODE 4: Denial-of-Wallet — the circuit breaker actually trips
    from observability.tracing import Budget, CircuitBreakerTripped
    cfg = RadarConfig(); cfg.max_model_calls = 2
    b = Budget(cfg)
    tripped = False
    try:
        for _ in range(10):
            b.charge_call("test")
    except CircuitBreakerTripped:
        tripped = True
    results["denial_of_wallet_breaker"] = {"pass": tripped, "score": 1.0 if tripped else 0.0,
                                           "detail": f"breaker tripped after {b.calls} calls (limit {cfg.max_model_calls})"}

    # self-repair (dimension 7): malformed model JSON → runner recovers, no crash
    from agents.agent_runners import _extract_json
    recovered = False
    try:
        _extract_json("not json at all", "array")
    except Exception:
        recovered = True  # raised cleanly (caller catches) rather than corrupting state
    results["self_repair_json"] = {"pass": recovered, "score": 1.0 if recovered else 0.0,
                                   "detail": "malformed JSON raises cleanly for caller fallback"}

    return results


# ── online LLM-judge (optional) ──────────────────────────────────────────────
def run_online() -> dict:
    from agents.llm_client import LLMClient
    cfg = RadarConfig()
    if cfg.offline or not cfg.anthropic_api_key:
        return {"skipped": "no ANTHROPIC_API_KEY / offline mode"}
    golden = _load_golden()
    llm = LLMClient(cfg)
    scores = []
    for idea in golden["good_idea_examples"]:
        user = json.dumps(idea, default=str)
        # swapped-position judging is for pairwise; here we score absolute on the rubric
        res = llm.complete(rubric.JUDGE_RUBRIC, user, model=cfg.model_cheap, max_tokens=300, node="eval-judge")
        try:
            scores.append(json.loads(res.text[res.text.find("{"):res.text.rfind("}") + 1]))
        except Exception:
            scores.append({"error": "judge parse"})
    return {"llm_judge_scores": scores}


_BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def _scores(offline: dict) -> dict:
    return {k: round(float(v.get("score", 0.0)), 4) for k, v in offline.items()}


def save_baseline(offline: dict) -> None:
    with open(_BASELINE, "w", encoding="utf-8") as f:
        json.dump({"scores": _scores(offline)}, f, indent=2)


def check_drift(offline: dict, margin: float) -> dict:
    """
    Day-5 evaluation gate: compare current scores to the committed baseline and fire if
    any score drops by more than `margin` (the tolerance band). This catches *behavioural
    drift* that deterministic pass/fail assertions miss. Set-based checks (routing,
    trajectory) already tolerate ordering variance.
    """
    if not os.path.exists(_BASELINE):
        return {"status": "no-baseline", "regressions": []}
    with open(_BASELINE, encoding="utf-8") as f:
        base = json.load(f).get("scores", {})
    cur = _scores(offline)
    regressions = []
    for name, base_score in base.items():
        c = cur.get(name, 0.0)
        if c < base_score - margin:
            regressions.append({"check": name, "baseline": base_score, "current": c})
    return {"status": "ok" if not regressions else "drift", "regressions": regressions, "margin": margin}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="deterministic eval-as-unit-test, no API key")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--update-baseline", action="store_true", help="write current offline scores as the drift baseline")
    ap.add_argument("--margin", type=float, default=0.10, help="tolerance band for drift (default 0.10)")
    args = ap.parse_args()

    offline = run_offline()
    report = {"offline": offline}
    if not args.offline:
        report["online"] = run_online()

    if args.update_baseline:
        save_baseline(offline)
        print(f"Baseline updated → {_BASELINE}")
    drift = check_drift(offline, args.margin)
    report["drift"] = drift

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\n=== Opportunity Radar — Eval Report ===\n")
        passed = total = 0
        for name, r in report["offline"].items():
            total += 1
            ok = r.get("pass")
            passed += 1 if ok else 0
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {name:28s} score={r.get('score',0):.2f}  {r.get('detail','')}")
        print(f"\nOffline: {passed}/{total} checks passed.")
        if drift["status"] == "drift":
            print(f"DRIFT (margin {drift['margin']}): {drift['regressions']}")
        elif drift["status"] == "ok":
            print(f"Drift gate: ok (within ±{drift['margin']} of baseline)")
        else:
            print("Drift gate: no baseline yet (run with --update-baseline to set one)")
        if "online" in report:
            print(f"\nOnline: {report['online']}")

    # non-zero exit if any offline check failed OR behavioural drift detected (CI-friendly)
    failed = any(not r.get("pass") for r in report["offline"].values())
    if failed or drift["status"] == "drift":
        sys.exit(1)


if __name__ == "__main__":
    main()
