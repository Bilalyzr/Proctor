"""CLI: ``python -m framework.gate_runner [--release] [--tier critical]``.

Runs the pyramid bottom-up against ``thresholds/<tier>.yaml`` (Rule 3), writes
a verdict to ``reports/`` and exits non-zero on failure. In ``--release`` mode
a matching human sign-off record (GOV-1) must exist or the gate fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from framework.config import Settings
from framework.gates import run_gates, write_verdict
from framework.signoff import verdict_passed, verify_signoff
from framework.thresholds import load_thresholds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AI testing pyramid gates")
    parser.add_argument("--tier", default=None, help="risk tier (default: AIQA_TIER)")
    parser.add_argument("--release", action="store_true", help="require a human sign-off record")
    args = parser.parse_args(argv)

    settings = Settings(_env_file=None)
    tier = args.tier or settings.tier
    thresholds = load_thresholds(tier, settings.thresholds_dir)

    print(f"[gate] tier={tier} thresholds_version={thresholds.version}")
    verdict = run_gates(thresholds)
    verdict_path = write_verdict(verdict)
    for result in verdict.results:
        detail = ""
        if result.details.get("branch_coverage") is not None:
            detail = (
                f" branch_coverage={result.details['branch_coverage']}% "
                f"(min {result.details['min_branch_coverage']}%)"
            )
        elif result.status == "not_built":
            detail = " (layer arrives in a later build phase)"
        print(f"[gate] {result.layer}: {result.status}{detail}")
    print(f"[gate] verdict passed={verdict.passed} stopped_at={verdict.stopped_at}")
    print(f"[gate] written: {verdict_path}")

    if not verdict.passed:
        return 1

    if args.release:
        signoff = Path("reports/signoffs/latest.md")
        if not verify_signoff(
            signoff,
            thresholds_path=Path(settings.thresholds_dir) / f"{tier}.yaml",
            verdict_path=verdict_path,
        ):
            print(
                "[gate] RELEASE BLOCKED: no sign-off record matching the current "
                "thresholds/verdict (GOV-1: humans sign off releases). "
                "See framework/signoff.py."
            )
            return 2
        if not verdict_passed(verdict_path):
            print("[gate] RELEASE BLOCKED: gate verdict did not pass.")
            return 3
        print("[gate] release approved with human sign-off on record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
