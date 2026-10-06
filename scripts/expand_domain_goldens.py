"""Deepen per-domain golden sets by sweeping context boundaries.

For every catalog golden row, each numeric/boolean context key is swept
across its decision-relevant boundary values; the pack's own policy engine
computes the expected action, so every generated row is
policy-consistent-by-construction while exercising the fact extractors and
rule boundaries with NEW combinations. Rows carry category prefix 'gen-'
so human reviewers can spot and re-verify them (registry notes provenance).

Run: .venv/Scripts/python scripts/expand_domain_goldens.py --min-cases 15
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from domains.registry import list_packs, load_pack_golden

REPO = Path(__file__).resolve().parents[1]


def _coerce(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re_luhn(value):
        return int(value)
    if is_float(value):
        return float(value)
    return value


def re_luhn(value: str) -> bool:
    return value.lstrip("-").isdigit()


def is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def context_variants(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Boundary sweep: nudge each numeric key around its value; flip booleans."""
    variants = [dict(context)]
    for key, value in context.items():
        if isinstance(value, bool):
            flipped = dict(context)
            flipped[key] = not value
            variants.append(flipped)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            for delta in (-1, 0, 1):
                nudged = dict(context)
                nudged[key] = value + delta
                variants.append(nudged)
            if value > 2:
                doubled = dict(context)
                doubled[key] = value * 2
                variants.append(doubled)
    return variants


def expected_for(pack: Any, text: str, context: dict[str, Any]) -> str | None:
    facts = pack.policy.parse(text, context)
    decision = pack.policy.evaluate(facts)
    action = getattr(decision, "action", None)
    return str(getattr(action, "value", action)) if action else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-cases", type=int, default=15)
    args = parser.parse_args(argv)

    total_added = 0
    for pack in list_packs():
        if pack.golden_csv is None or not pack.golden_csv.exists():
            continue
        rows = load_pack_golden(pack)
        seen_sigs = {(row["text"], row.get("context", ""), row["expected_action"]) for row in rows}
        used_ids = {row["case_id"] for row in rows}
        state = {"counter": 0}
        additions: list[dict[str, str]] = []

        def add_row(
            text: str,
            variant_str: str,
            expected: str,
            row: dict,
            _seen: set = seen_sigs,
            _used: set = used_ids,
            _state: dict = state,
            _additions: list = additions,
        ) -> None:
            signature = (text, variant_str, expected)
            if signature in _seen:
                return
            _seen.add(signature)
            _state["counter"] += 1
            case_id = f"{row['case_id']}-g{_state['counter']}"
            while case_id in _used:  # idempotent across repeated runs
                _state["counter"] += 1
                case_id = f"{row['case_id']}-g{_state['counter']}"
            _used.add(case_id)
            category = row.get("category") or "gen"
            _additions.append(
                {
                    "case_id": case_id,
                    "text": text,
                    "context": variant_str,
                    "expected_action": expected,
                    "category": f"gen-{category}",
                }
            )

        needed = args.min_cases - len(rows)
        if needed <= 0:
            continue

        # pass 1: context boundary sweeps
        for row in rows:
            context = {}
            if row.get("context"):
                for pair in row["context"].split(";"):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        context[key.strip()] = _coerce(value.strip())
            for variant in context_variants(context):
                if len(additions) >= needed:
                    break
                variant_str = ";".join(
                    f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                    for key, value in sorted(variant.items())
                )
                expected = expected_for(pack, row["text"], variant)
                if expected is not None:
                    add_row(row["text"], variant_str, expected, row)
            if len(additions) >= needed:
                break

        # pass 2: paraphrase wrappers (robustness rows for packs with no
        # context keys); policy engine decides expected for each wrapper
        wrappers = [
            "hello, {t}",
            "please {t}",
            "urgent: {t}",
            "{t} thanks",
            "Hi there! {t}",
        ]
        if len(additions) < needed:
            for row in rows:
                for wrapper in wrappers:
                    if len(additions) >= needed:
                        break
                    text = wrapper.format(t=row["text"])
                    variant_str = row.get("context", "")
                    context = {}
                    if variant_str:
                        for pair in variant_str.split(";"):
                            if "=" in pair:
                                key, value = pair.split("=", 1)
                                context[key.strip()] = _coerce(value.strip())
                    expected = expected_for(pack, text, context)
                    if expected is not None:
                        add_row(text, variant_str, expected, row)
                if len(additions) >= needed:
                    break
        if additions:
            with pack.golden_csv.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["case_id", "text", "context", "expected_action", "category"],
                )
                writer.writerows(additions)
            total_added += len(additions)
            print(f"{pack.id:<14} +{len(additions)} (now {len(rows) + len(additions)})")
    print(f"total added: {total_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
