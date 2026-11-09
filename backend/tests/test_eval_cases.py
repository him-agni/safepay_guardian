"""The evaluation set is well formed, and the rules-only floor holds on it (no network)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.risk.engine import HybridEngine
from app.risk.types import LEVEL_ORDER

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
CITE_TYPES = {"gift_card", "crypto_or_wire", "urgency", "secrecy", "authority_threat", "new_payee", "amount",
              "whitelist_request", "changed_contact", "no_context", "impersonation", "safe_account"}


def _runner():
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_cases_are_well_formed():
    cases = DATA["cases"]
    assert len(cases) == 16
    assert len({c["id"] for c in cases}) == 16
    groups = [c["group"] for c in cases]
    assert (groups.count("legit"), groups.count("scam"), groups.count("ambiguous"), groups.count("adversarial")) \
        == (4, 6, 3, 3)
    for c in cases:
        assert c["expect"]["levels"] and set(c["expect"]["levels"]) <= set(LEVEL_ORDER)
        assert c["payee"]["status"] in ("new", "known", "trusted")
        for token in c["expect"]["cite"]:
            kind, value = token.split(":")
            assert kind in ("type", "family") and (kind == "family" or value in CITE_TYPES), token


def test_rules_only_floor_on_the_eval_set():
    run_eval = _runner()
    engine = HybridEngine(None)
    levels = {c["id"]: engine.assess(run_eval.build_context(c, DATA["default_history_dollars"])).level
              for c in DATA["cases"]}
    # Hard rules hold these on their own, with or without the AI.
    for case_id in ("S1", "D1", "D2"):
        assert levels[case_id] == "high", case_id
    # The rules alone never hold a legitimate payment.
    assert all(levels[c["id"]] != "high" for c in DATA["cases"] if c["group"] == "legit")
