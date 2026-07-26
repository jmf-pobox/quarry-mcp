"""Tests for the enable/disable CLI summary presenters."""

from __future__ import annotations

from quarry.enable import DisableResult, EnableResult
from quarry.enable_report import DisableReport, EnableReport


def test_enable_report_lists_claudemd_steps() -> None:
    result = EnableResult(
        directory="/p",
        collection="p",
        captures_collection="p-captures",
        config_path="/p/.punt-labs/quarry/config.md",
        guide_deposited=True,
        enabled_marker_written=True,
        import_registered=True,
        legacy_block_stripped=True,
    )
    lines = EnableReport(result).lines()
    assert lines[0] == "Enabled quarry for /p"
    joined = "\n".join(lines)
    assert "Deposited quarry guide" in joined
    assert "Registered @.punt-labs/quarry/CLAUDE.md" in joined
    assert "Removed legacy quarry block" in joined


def test_enable_report_omits_absent_steps() -> None:
    result = EnableResult(
        directory="/p", collection="p", captures_collection="p-captures"
    )
    joined = "\n".join(EnableReport(result).lines())
    assert "Registered @" not in joined
    assert "Removed legacy" not in joined


def test_enable_report_reports_ethos_skipped() -> None:
    result = EnableResult(
        directory="/p",
        collection="p",
        captures_collection="p-captures",
        ethos_skipped=True,
    )
    joined = "\n".join(EnableReport(result).lines())
    assert "Ethos: not installed (agent memory skipped)" in joined


def test_enable_report_reports_ethos_failed() -> None:
    result = EnableResult(
        directory="/p",
        collection="p",
        captures_collection="p-captures",
        ethos_failed=["rmh"],
    )
    assert any("Ethos FAILED: rmh" in line for line in EnableReport(result).lines())


def test_disable_report_purge_queued_when_not_keep_data() -> None:
    result = DisableResult(
        directory="/p",
        collection="p",
        captures_collection="p-captures",
        removed=3,
        import_pruned=True,
        enabled_marker_removed=True,
    )
    joined = "\n".join(DisableReport(result, keep_data=False).lines())
    assert "Deregistered p (3 files); chunk purge queued" in joined
    assert "Removed @.punt-labs/quarry/CLAUDE.md" in joined
    assert "Removed enabled marker (guide left dormant)" in joined


def test_disable_report_keeps_data_when_flag_set() -> None:
    result = DisableResult(
        directory="/p", collection="p", captures_collection="p-captures", removed=3
    )
    joined = "\n".join(DisableReport(result, keep_data=True).lines())
    assert "kept indexed data" in joined


def test_disable_report_idempotent_noop() -> None:
    result = DisableResult(directory="/p", collection="", captures_collection="")
    joined = "\n".join(DisableReport(result, keep_data=False).lines())
    assert "Already disabled (no registration)" in joined
