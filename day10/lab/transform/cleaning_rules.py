from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

_UNCLEAR_PREFIX = "Nội dung không rõ ràng"
_STALE_HR_ANNUAL = "10 ngày phép năm"
_STALE_REFUND_TEXT = "14 ngày làm việc"
_FIXED_REFUND_TEXT = "7 ngày làm việc"


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _chunk_id(doc_id: str, text: str, seq: int) -> str:
    digest = hashlib.sha256(f"{doc_id}|{text}|{seq}".encode()).hexdigest()[:16]
    return f"{doc_id}_{seq}_{digest}"


def _parse_date(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", ""
    return "", "invalid_effective_date_format"


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    quarantine: List[Dict[str, Any]] = []
    seen: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    def drop(row: Dict, reason: str, **extra: Any) -> None:
        quarantine.append({**row, "reason": reason, **extra})

    for row in rows:
        doc_id = row.get("doc_id", "")
        text = row.get("chunk_text", "")
        eff_raw = row.get("effective_date", "")
        exported_at = row.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            drop(row, "unknown_doc_id")
            continue

        eff, err = _parse_date(eff_raw)
        if err == "empty_effective_date":
            drop(row, "missing_effective_date")
            continue
        if err:
            drop(row, err, effective_date_raw=eff_raw)
            continue

        if not text.strip():
            drop(row, "empty_chunk_text")
            continue

        if text.startswith(_UNCLEAR_PREFIX):
            drop(row, "unclear_content_marker")
            continue

        if doc_id == "hr_leave_policy" and eff < "2026-01-01":
            drop(row, "stale_hr_policy_effective_date", effective_date_normalized=eff)
            continue

        if doc_id == "hr_leave_policy" and _STALE_HR_ANNUAL in text:
            drop(row, "stale_hr_annual_leave_content", effective_date_normalized=eff)
            continue

        key = _norm_text(text)
        if key in seen:
            drop(row, "duplicate_chunk_text")
            continue
        seen.add(key)

        final_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4" and _STALE_REFUND_TEXT in text:
            final_text = text.replace(_STALE_REFUND_TEXT, _FIXED_REFUND_TEXT) + " [cleaned: stale_refund_window]"

        seq += 1
        cleaned.append(
            {
                "chunk_id": _chunk_id(doc_id, final_text, seq),
                "doc_id": doc_id,
                "chunk_text": final_text,
                "effective_date": eff,
                "exported_at": exported_at,
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    if not rows:
        path.write_text(",".join(fields) + "\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    seen_k: set[str] = set()
    fields: List[str] = []
    for r in rows:
        for k in r:
            if k not in seen_k:
                seen_k.add(k)
                fields.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
