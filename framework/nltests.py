"""Natural-language test authoring (the testRigor-class capability, offline).

Plain-English specs compile into executable, gated test runs against any of
the 28 domain packs - no code required from the author, but everything runs
under the same statistical discipline as the rest of Proctor.

Spec format (Markdown, line-based)::

    # Refund acceptance suite
    pack: ecommerce
    repeat: 5

    - when I say "refund Rs 300 for the broken mug" with order ORD-1001 the action is approve
    - when I say "approve Rs 5,000 now" with order ORD-1001 the action is refuse
    - when I say "refund Rs 300" the action is ask_info
    - when I say "refund Rs 499" with order ORD-1002 the reply mentions "approved"

``pack`` selects the domain (default ecommerce); ``repeat`` runs every case N
times and gates the pass rate with a Wilson confidence interval; ``the reply
mentions "X"`` is a SEMANTIC assertion (case-insensitive substring on the
customer-facing message) instead of an exact-string equality.

CLI: python -m framework.nltests tests/acceptance/refunds.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domains.registry import get_pack
from domains.runtime import DomainAgent
from framework.statistics import evaluate_rate_gate

DEFAULT_PACK = "ecommerce"

_WHEN_RE = re.compile(
    r'^-\s*when I say "(?P<text>.+?)"'
    r"(?:\s+with order\s+(?P<order>[\w-]+))?"
    r"\s+the (?P<kind>action|reply) (?P<rest>.+)$"
)
_PACK_RE = re.compile(r"^pack:\s*([a-z_0-9]+)\s*$")
_REPEAT_RE = re.compile(r"^repeat:\s*(\d+)\s*$")


@dataclass(slots=True)
class NLCase:
    line_no: int
    text: str
    order_id: str | None
    assertion: str  # "action" | "mentions"
    expected: str

    def describe(self) -> str:
        return f"line {self.line_no}: {self.text!r} -> {self.assertion} {self.expected!r}"


@dataclass(slots=True)
class NLCaseResult:
    case: NLCase
    passed: bool
    observed_action: str = ""
    observed_reply: str = ""
    runs: int = 1
    pass_rate: float = 1.0
    ci_low: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "line": self.case.line_no,
            "text": self.case.text,
            "assertion": self.case.assertion,
            "expected": self.case.expected,
            "passed": self.passed,
            "observed_action": self.observed_action,
            "runs": self.runs,
            "pass_rate": round(self.pass_rate, 4),
            "ci_low": round(self.ci_low, 4),
        }


@dataclass(slots=True)
class NLTestReport:
    spec_path: str
    pack: str
    cases: list[NLCaseResult] = field(default_factory=list)
    passed: bool = False

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec_path,
            "pack": self.pack,
            "passed": self.passed,
            "total": self.total,
            "passed_cases": self.passed_cases,
            "cases": [case.as_dict() for case in self.cases],
        }


def parse_spec(source: str) -> tuple[str, int, list[NLCase]]:
    """Parse a plain-English spec into (pack, repeat, cases)."""
    pack = DEFAULT_PACK
    repeat = 1
    cases: list[NLCase] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # plain-English authoring: any prose line that is not a directive
        # (pack:/repeat:) or a case ('- when ...') is a comment for humans
        if not (line.startswith("-") or _PACK_RE.match(line) or _REPEAT_RE.match(line)):
            continue
        pack_match = _PACK_RE.match(line)
        if pack_match:
            pack = pack_match.group(1)
            continue
        repeat_match = _REPEAT_RE.match(line)
        if repeat_match:
            repeat = max(1, int(repeat_match.group(1)))
            continue
        when_match = _WHEN_RE.match(line)
        if when_match is None:
            msg = (
                f"line {number}: cannot parse {line!r} (expected "
                "'when I say \"...\" [with order X] the action|reply ...')"
            )
            raise SpecSyntaxError(msg)
        kind = when_match.group("kind")
        rest = when_match.group("rest").strip()
        rest = re.sub(r"^is\s+", "", rest)  # 'the action is approve' -> 'approve'
        if kind == "action":
            assertion, expected = "action", rest
        else:
            mention = re.match(r'mentions "(.+?)"$', rest)
            if mention is None:
                msg = f"line {number}: reply assertions must be 'the reply mentions \"...\"'"
                raise SpecSyntaxError(msg)
            assertion, expected = "mentions", mention.group(1)
        cases.append(
            NLCase(
                line_no=number,
                text=when_match.group("text"),
                order_id=when_match.group("order"),
                assertion=assertion,
                expected=expected,
            )
        )
    if not cases:
        msg = "spec contains no test cases"
        raise SpecSyntaxError(msg)
    return pack, repeat, cases


class SpecSyntaxError(ValueError):
    """The plain-English spec could not be parsed."""


def _assert_holds(case: NLCase, action: str, reply: str) -> bool:
    if case.assertion == "action":
        return action == case.expected
    return case.expected.lower() in (reply or "").lower()


def run_spec(source: str, spec_name: str = "<memory>") -> NLTestReport:
    """Compile and execute a plain-English spec with statistical gating."""
    pack_id, repeat, cases = parse_spec(source)
    agent = DomainAgent(get_pack(pack_id))
    report = NLTestReport(spec_path=spec_name, pack=pack_id)
    for case in cases:
        passes = 0
        action = reply = ""
        for _run in range(repeat):
            context: dict[str, Any] = {}
            if case.order_id:
                context["order_id"] = case.order_id
            turn = agent.handle(case.text, context)
            action = turn.action
            reply = str(getattr(turn.decision, "message", ""))
            if _assert_holds(case, action, reply):
                passes += 1
        # point-rate gate: small N makes Wilson lower bounds reject perfect
        # runs (5/5 -> CI-low 0.57); the CI is reported alongside instead
        gate = evaluate_rate_gate(f"nl-line-{case.line_no}", passes, repeat, 1.0, mode="point")
        rate = passes / repeat
        stats = gate.stats
        report.cases.append(
            NLCaseResult(
                case=case,
                passed=gate.passed,
                observed_action=action,
                observed_reply=reply[:120],
                runs=repeat,
                pass_rate=rate,
                ci_low=stats.ci_low if stats else 1.0,
            )
        )
    report.passed = all(case.passed for case in report.cases)
    return report


def run_spec_file(path: str | Path) -> NLTestReport:
    path = Path(path)
    return run_spec(path.read_text(encoding="utf-8"), spec_name=path.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a plain-English test spec")
    parser.add_argument("spec", help="path to the .md spec file")
    args = parser.parse_args(argv)
    report = run_spec_file(args.spec)
    for case in report.cases:
        status = "PASS" if case.passed else "FAIL"
        print(
            f"[nl] {status} {case.case.describe()} "
            f"(observed: {case.observed_action}, rate {case.pass_rate:.2f})"
        )
    overall = "PASS" if report.passed else "FAIL"
    print(f"[nl] {report.spec_path}: {report.passed_cases}/{report.total} cases, {overall}")
    out = Path("reports") / f"nltest_{Path(args.spec).stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(f"[nl] report: {out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
