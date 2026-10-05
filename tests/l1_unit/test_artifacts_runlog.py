"""Rank-1 unit tests: artifact versioning (AST-1) and structured run logging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.artifacts import manifest_digest, sha256_bytes, sha256_file, sha256_text, snapshot
from framework.runlog import RunLogger, read_run

pytestmark = pytest.mark.l1


def test_sha256_helpers_agree(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("hello", encoding="utf-8")
    assert sha256_file(file) == sha256_text("hello") == sha256_bytes(b"hello")
    assert len(sha256_text("x")) == 64


def test_snapshot_hashes_files_with_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("alpha", encoding="utf-8")
    (root / "sub" / "b.md").write_text("beta", encoding="utf-8")
    manifest = snapshot({"corpus": root})
    assert set(manifest["corpus"]) == {"a.md", "sub/b.md"}
    assert manifest["corpus"]["a.md"] == sha256_text("alpha")


def test_snapshot_accepts_single_file(tmp_path: Path) -> None:
    file = tmp_path / "one.yaml"
    file.write_text("tier: critical\n", encoding="utf-8", newline="\n")
    manifest = snapshot({"thresholds": file})
    assert manifest["thresholds"] == {"one.yaml": sha256_text("tier: critical\n")}


def test_snapshot_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        snapshot({"gone": tmp_path / "does-not-exist"})


def test_manifest_digest_is_order_independent() -> None:
    a = {"x": {"f": "1"}}
    b = {"x": {"f": "1"}}
    assert manifest_digest(a) == manifest_digest(b)
    assert manifest_digest(a) != manifest_digest({"x": {"f": "2"}})


class TestRunLogger:
    def test_full_run_lifecycle(self, tmp_path: Path) -> None:
        artifacts = snapshot_root_with_file(tmp_path)
        with RunLogger(
            log_dir=tmp_path / "reports",
            suite="l1",
            run_id="fixed-id",
            params={"provider": "mock", "seed": 42},
            artifacts=artifacts,
        ) as logger:
            logger.log_case("case-1", "pass", layer="l1", req_ids=["EVL-5"])
            logger.log_case("case-2", "fail", layer="l1")
            logger.log_case("case-3", "weird-status")  # unknown -> counted as error

        run_path = tmp_path / "reports" / "runs" / "fixed-id.jsonl"
        records = read_run(run_path)
        types = [r["type"] for r in records]
        assert types[0] == "run_start"
        assert types[-1] == "run_end"
        assert types.count("case") == 3

        header = records[0]
        assert header["suite"] == "l1"
        assert header["params"]["provider"] == "mock"
        assert header["artifact_digest"] == manifest_digest(artifacts)

        footer = records[-1]
        assert footer["pass_count"] == 1
        assert footer["fail_count"] == 1
        assert footer["error_count"] == 1  # 'weird-status' bucketed as error
        assert footer["total"] == 3
        assert footer["duration_s"] >= 0

        case_records = [r for r in records if r["type"] == "case"]
        assert case_records[0]["req_ids"] == ["EVL-5"]
        assert case_records[0]["ts"]

    def test_manifest_file_written_next_to_run(self, tmp_path: Path) -> None:
        artifacts = snapshot_root_with_file(tmp_path)
        logger = RunLogger(
            log_dir=tmp_path / "reports",
            suite="l1",
            run_id="with-manifest",
            artifacts=artifacts,
        )
        logger.open()
        logger.close()
        manifest_path = tmp_path / "reports" / "manifests" / "with-manifest.json"
        assert manifest_path.exists()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["run_id"] == "with-manifest"
        assert "corpus" in payload["artifacts"]

    def test_close_is_idempotent_and_open_implicit(self, tmp_path: Path) -> None:
        logger = RunLogger(log_dir=tmp_path / "reports", suite="l1", run_id="twice")
        logger.log_case("only", "pass")  # implicit open
        first = logger.close()
        second = logger.close()
        assert first["total"] == second["total"] == 1
        records = read_run(tmp_path / "reports" / "runs" / "twice.jsonl")
        assert [r["type"] for r in records] == ["run_start", "case", "run_end"]

    def test_summary_before_any_case(self, tmp_path: Path) -> None:
        logger = RunLogger(log_dir=tmp_path / "reports", suite="l1")
        assert logger.summary()["total"] == 0


def snapshot_root_with_file(tmp_path: Path) -> dict[str, dict[str, str]]:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "doc.md").write_text("policy", encoding="utf-8")
    return snapshot({"corpus": root})
