from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str
    detail: str


def _check(name: str, passed: bool, severity: str, detail: str) -> ExpectationResult:
    return ExpectationResult(name=name, passed=passed, severity=severity, detail=detail)


def run_expectations(rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    results: List[ExpectationResult] = []

    results.append(_check(
        "min_one_row",
        len(rows) >= 1,
        "halt",
        f"cleaned_rows={len(rows)}",
    ))

    empty_doc = [r for r in rows if not (r.get("doc_id") or "").strip()]
    results.append(_check(
        "no_empty_doc_id",
        len(empty_doc) == 0,
        "halt",
        f"empty_doc_id_count={len(empty_doc)}",
    ))

    stale_refund = [
        r for r in rows
        if r.get("doc_id") == "policy_refund_v4" and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    results.append(_check(
        "refund_no_stale_14d_window",
        len(stale_refund) == 0,
        "halt",
        f"violations={len(stale_refund)}",
    ))

    short_chunks = [r for r in rows if len(r.get("chunk_text") or "") < 8]
    results.append(_check(
        "chunk_min_length_8",
        len(short_chunks) == 0,
        "warn",
        f"short_chunks={len(short_chunks)}",
    ))

    bad_dates = [
        r for r in rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    results.append(_check(
        "effective_date_iso_yyyy_mm_dd",
        len(bad_dates) == 0,
        "halt",
        f"non_iso_rows={len(bad_dates)}",
    ))

    stale_hr = [
        r for r in rows
        if r.get("doc_id") == "hr_leave_policy" and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    results.append(_check(
        "hr_leave_no_stale_10d_annual",
        len(stale_hr) == 0,
        "halt",
        f"violations={len(stale_hr)}",
    ))

    sop_chunks = [r for r in rows if r.get("doc_id") == "access_control_sop"]
    results.append(_check(
        "access_control_sop_present",
        len(sop_chunks) >= 1,
        "halt",
        f"access_control_sop_chunks={len(sop_chunks)}",
    ))

    unclear = [
        r for r in rows
        if (r.get("chunk_text") or "").startswith("Nội dung không rõ ràng")
    ]
    results.append(_check(
        "no_unclear_content_marker",
        len(unclear) == 0,
        "halt",
        f"unclear_content_chunks={len(unclear)}",
    ))

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
