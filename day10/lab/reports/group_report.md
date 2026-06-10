# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:**  

**Ngày nộp:** 2026-06-10  
**Repo:** day10-hoa  
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

Pipeline nhận `data/raw/policy_export_dirty.csv` (247 rows từ nhiều nguồn, bao gồm export hợp lệ và các bản lỗi/legacy). Luồng chuẩn: **ingest → clean (allowlist + date normalize + content filter) → validate (8 expectations) → embed (Chroma upsert idempotent)**.

- `run_id` được ghi trên dòng đầu log và trong `artifacts/manifests/manifest_<run_id>.json`.
- Pipeline **HALT có kiểm soát** khi bất kỳ expectation `severity=halt` nào fail — không embed dữ liệu bẩn.
- Embed **idempotent**: `chunk_id` được tính từ SHA256(doc_id|text|seq), upsert + prune id cũ → rerun nhiều lần không phình collection (count=37 ổn định).
- Grading chạy với `--top-k 8` để đảm bảo các chunk ít phổ biến vẫn được retrieval.

**Lệnh chạy:**

```bash
python etl_pipeline.py run && python grading_run.py --out artifacts/eval/grading_clean.jsonl --top-k 8
```

---

## 2. Cleaning & expectation (150–200 từ)

Baseline có các rule: allowlist doc_id, normalize effective_date → ISO, quarantine HR stale `eff < 2026-01-01`, quarantine chunk_text rỗng, dedupe, fix refund 14→7 ngày.

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước (số liệu) | Sau (số liệu) | Chứng cứ |
|------------------------|-----------------|---------------|----------|
| **Rule+1**: `access_control_sop` vào allowlist | `cleaned_records≈31`, E7 `access_control_sop_present` FAIL | `cleaned_records=37` (+6), E7 OK `access_control_sop_chunks=6` | log `run_id=clean-run`; grading 10/10 |
| **Rule+2**: HR content filter `10 ngày phép năm` (stale bất kể effective_date) | `hr_leave_no_stale_10d_annual violations>0` → PIPELINE_HALT | `violations=0` — PIPELINE_OK | log `run_id=post-fix` |
| **Rule+3**: empty/whitespace chunk_text | whitespace-only rows lọt qua do `if not text:` chỉ bắt chuỗi rỗng | các row `"    "` bị quarantine với reason `empty_chunk_text` | `artifacts/quarantine/quarantine_post-fix.csv` |
| **Rule+4**: `unclear_content_marker` | chunk `"Nội dung không rõ ràng..."` lọt vào embed gây nhiễu retrieval | quarantine với reason `unclear_content_marker`, E8 `no_unclear_content_marker` OK | log `run_id=post-fix` |
| **E7**: `access_control_sop_present` (halt) | FAIL khi thiếu Rule+1 | `access_control_sop_chunks=6` — OK | log expectation suite |
| **E8**: `no_unclear_content_marker` (halt) | FAIL khi thiếu Rule+4 | `unclear_content_chunks=0` — OK | log expectation suite |

**Expectation fail đáng chú ý:**

Pipeline ban đầu HALT do `hr_leave_no_stale_10d_annual violations>0`. Nguyên nhân: baseline chỉ lọc theo `effective_date < 2026-01-01`, nhưng một số chunk bản HR 2025 (nội dung "10 ngày phép năm") được export với `effective_date` năm 2026. Sửa bằng Rule+2: content filter → violations=0 → PIPELINE_OK.

---

## 3. Before / after ảnh hưởng retrieval (200–250 từ)

**Kịch bản inject:**

```bash
python etl_pipeline.py run --no-refund-fix --skip-validate --run-id inject-corrupt
```

- `--no-refund-fix`: giữ nguyên chunk "14 ngày làm việc" (cửa sổ hoàn tiền sai) không bị fix.
- `--skip-validate`: bypass expectation halt `refund_no_stale_14d_window violations=2` → chunk bẩn được embed.
- Log ghi `WARN: expectation failed but --skip-validate → tiếp tục embed`, `embed_prune_removed=2` (chunk bẩn thay thế chunk sạch).

**Kết quả định lượng:**

| Trạng thái | Pass/Total | `hits_forbidden` | File evidence |
|------------|-----------|------------------|---------------|
| Before inject (clean) | 10/10 (100%) | 0 | `artifacts/eval/grading_clean.jsonl` |
| After inject corrupt | 8/10 (80%) | **1** (`gq_d10_01`) | `artifacts/eval/grading_inject.jsonl` |
| After fix (clean) | 10/10 (100%) | 0 | `artifacts/eval/grading_post_fix.jsonl` |

**Phân tích:** Inject tạo `hits_forbidden=True` trên `gq_d10_01` (câu hỏi về cửa sổ hoàn tiền) — retrieval trả về chunk "14 ngày làm việc" thay vì "7 ngày". Ngoài ra `gq_d10_06` (escalation P1) fail do chunk stale refund chiếm slot top-k đẩy chunk SLA ra ngoài top-8. Đây là bằng chứng pipeline cleaning bảo vệ chất lượng agent: không có expectation halt + fix rule, agent sẽ trả lời sai về chính sách hoàn tiền.

Sau khi chạy lại clean: `embed_prune_removed=2` xóa 2 chunk bẩn khỏi collection → grading về 10/10, `hits_forbidden=0`.

---

## 4. Freshness & monitoring (100–150 từ)

**SLA chọn:** `FRESHNESS_SLA_HOURS=24` — phù hợp cho corpus policy cập nhật theo ngày làm việc.

**Kết quả trên manifest:**
```
freshness_check=FAIL {"latest_exported_at": "2026-04-11T00:00:00", "age_hours": 1452.94, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

**Ý nghĩa PASS/FAIL:**
- **PASS**: `age_hours ≤ 24` — corpus tươi, agent an toàn phục vụ.
- **FAIL**: `age_hours > 24` — corpus vượt SLA, cần alert on-call và kiểm tra lại pipeline.
- Data lab luôn FAIL (~1452h) vì `exported_at` cố định ở `2026-04-11` — **hành vi đúng theo thiết kế** để minh họa freshness monitoring.

**Lệnh kiểm tra:**
```bash
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_post-fix.json
```

---

## 5. Liên hệ Day 09 (50–100 từ)

Pipeline Day 10 dùng collection riêng `day10_kb` thay vì collection Day 09 để đảm bảo isolation: corpus Day 09 có thể chứa vector chưa qua cleaning pipeline — dùng chung sẽ làm eval grading sai.

Tích hợp thực tế: sau khi `etl_pipeline.py run` thành công (PIPELINE_OK, grading 10/10), có thể swap alias Chroma collection cho retrieval worker Day 09 trỏ sang `day10_kb`. Cùng domain (CS + IT + HR), cùng `data/docs/` — corpus Day 10 sạch hơn và version đúng.

---

## 6. Rủi ro còn lại & việc chưa làm

- **Rule versioning**: cutoff `2026-01-01` hardcode trong `cleaning_rules.py` — chưa đọc từ contract/env.
- **Freshness boundary thứ 2**: chỉ đo `exported_at` từ source, chưa đo thời điểm chunk visible trong Chroma sau upsert.
- **LLM-judge eval** chưa implement (bonus Distinction).
- **Peer review**: chưa điền — cần khi có nhóm khác đổi bài.
