# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Mọi con số lấy từ file do pipeline/script sinh ra (`out/poc/*`, `out/baseline/*`, `python -m tools.dev_selfcheck`).
> Repo học viên **không có Ground Truth** (`gt/` do giảng viên giữ) nên chưa có `reports/metrics_*.json` /
> `table1_baseline_vs_poc.md`; phần cần số đó ghi rõ là "chờ giảng viên chấm". Mục có dấu **[CẦN ĐIỀN]** là thông tin chỉ nhóm biết.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G03 |
| Challenge | T02 · Raw QC Triage (blur / glare / dark / compression) |
| Thành viên + vai trò | 1. Nguyễn Hoàn Thiện — nhóm một người (theo bài mẫu), đảm nhận toàn bộ vai trò (Lead/Integrator, Data, Core algorithm, QA/metric, Review + report); giả định nhóm một người như bài mẫu |
| Git URL | https://github.com/leejihoon-quant/K5-Day6-L2-NguyenHoanThien-2A202603123-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | `2c9fb26` (đóng băng code T02) |
| Tag `final-24h` (commit) | commit cuối trên `main` chứa báo cáo này (`git rev-parse final-24h`) |
| Deadline (giờ VN) | theo thông báo của giảng viên |

## 01 · Problem statement

- **Ai bị ảnh hưởng khi hệ thống sai?** Đội gán nhãn / huấn luyện model dùng ảnh thô từ xe. Ảnh mờ, cháy sáng, thiếu sáng hay nén quá tay lọt vào tập train làm nhãn và model sai; ngược lại loại nhầm ảnh ban đêm hữu ích làm mất độ phủ.
- **Điểm nghẽn cụ thể:** reviewer chỉ xem được B = 20 trong 40 ảnh mỗi lô, nên thứ tự ưu tiên quyết định số lỗi tìm được. Một ngưỡng Laplacian duy nhất (blur-only) bỏ sót glare, nén và báo nhầm camera cam_B quang học mềm.
- **Đầu vào → đầu ra:** vào `images.csv` + 96 ảnh JPEG; ra `out/poc/ranked_review.csv` (`image_id, score, pred_defect_type, pred_action`), `review_queue.csv`, `contact_sheet.html`, `decision.json`.
- **Tiêu chí GO / HOLD / REWORK (chốt trước khi chạy eval):** theo từng ảnh, `RECAPTURE` nếu ít nhất một detector vượt ngưỡng, ngược lại `KEEP`. Theo lô eval (`HOLD_FRACTION = 0.40`): 0 ảnh bị gắn cờ → `GO`; ≥ 40% bị gắn cờ → `HOLD` (nghi lỗi hệ thống ở chuỗi thu ảnh, không release lô); còn lại → `REWORK` (chỉ chụp lại ảnh bị cờ).
- **Giả định cần domain owner xác nhận:** (a) ngưỡng 40% cho HOLD là giả định của nhóm, chưa có dữ liệu vận hành để hiệu chỉnh; (b) ảnh ban đêm tối tự nhiên là hợp lệ, chỉ ảnh "ngày/hoàng hôn bị giảm gain" mới là lỗi dark.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 56 ảnh (14 cảnh × 4) | `fixtures/t02_raw_qc/` (do giảng viên cấp) | theo `manifest.csv` | Có |
| eval | 40 ảnh (10 cảnh × 4) | như trên | như trên | Có |

- **Schema:** `images.csv` = `image_id, path, camera_id, light, split`; split theo cảnh gốc (dev 60% / eval 40%). Camera cam_A / cam_B, ánh sáng day / dusk / night.
- **Seed:** 42 (PoC không dùng ngẫu nhiên). **`manifest.csv` verified (sha256):** có — `python -m tools.verify_manifests` → `14 manifests, 0 failing`.
- **Dữ liệu thật:** không dùng (`data/real/` không có). Mọi kết quả chỉ trên fixtures tổng hợp.
- **Nhãn dev tự gắn bằng mắt:** `reports/dev_labels.csv` (56 dòng: 28 sạch, 10 compression, 8 blur, 6 dark, 4 glare). Đây là đánh giá của nhóm, không phải GT chính thức; hai ảnh nén nhẹ (`img_09_3`, `img_12_2`) nhìn ban đầu giống ảnh sạch và chỉ được gắn nhãn compression sau khi đo blockiness.

## 03 · Research & design

- **Kỹ thuật và lý do:** đề (`docs/tracks/T02.md` §8) gợi ý kết hợp nhiều feature, chuẩn hoá theo camera, chấm theo vùng. PoC dùng 4 detector bổ sung nhau thay vì một ngưỡng: (1) **blur** = Laplacian variance chia cho phương sai độ sáng (chuẩn hoá tương phản → cam_B mềm và ảnh tối không bị coi là mờ); (2) **dark** = percentile 99.5 độ sáng (ảnh đêm vẫn có đèn sáng, ảnh ngày bị giảm gain thì không); (3) **glare** = diện tích vùng liên thông lớn nhất của pixel ≥ 235 (cháy **cục bộ**, đèn nhỏ ban đêm không đủ lớn); (4) **compression** = chênh gradient ở biên khối 8 px so với bên trong khối (JPEG blockiness). Mỗi detector được chuẩn hoá về 0.5 tại ngưỡng của nó, rồi lấy max.
- **Tài liệu tham khảo:** `docs/tracks/T02.md` và `src/common/image_ops.py` trong repo (đã xem 2026-11-15); không dùng nguồn ngoài.
- **Data flow:** `load` (kiểm manifest, đọc `images.csv`) → `process` (4 detector, `score`, `pred_defect_type`, `pred_action`) → `rank` (top-20 của split eval → `review_queue.csv` + `contact_sheet.html`) → `review` (áp quyết định reviewer, audit log) → `decide` (GO/HOLD/REWORK + `reason_code` + owner).
- **Thành phần offline:** không dùng model/weights; chỉ numpy, scipy, Pillow.
- **Trade-offs:** quy tắc thủ công dễ giải thích và chạy 0.5 giây cho 96 ảnh, nhưng ngưỡng đặt từ 56 ảnh dev nên có thể không bền với ảnh thật; chọn max thay vì tổng để một lỗi nặng không bị lỗi nhẹ khác làm loãng.

## 04 · Baseline vs PoC

- **Baseline** (`src/t02_baseline.py`): một ngưỡng Laplacian toàn ảnh, score = 1 / `lap_var`. Chạy: `python -m src.main --track t02 --pipeline src.t02_baseline --output out/baseline --run-name baseline --offline --seed 42`. Baseline phụ: random (`src/examples/random_baseline.py`, `--output out/baseline_random`).
- **PoC** (`src/pipeline.py`): 4 detector như §03. Chạy: `python -m src.main --config configs/lab.yaml --track t02 --output out/poc --run-name poc --offline --seed 42`.
- **Cùng budget / pool / seed:** xác nhận (B = 20, 40 ảnh eval, seed 42).

**Bảng 1 · Baseline vs PoC.** Chưa điền theo contract: `src.evaluate` cần `gt/labels.csv` (giảng viên giữ), nên chưa có `reports/metrics_*.json`. Chỉ số tự đo bằng nhãn dev tự gắn (**lạc quan**, vì ngưỡng PoC được chọn trên chính split dev):

| Chỉ số (dev, 56 ảnh, 28 lỗi, B = 20) | Random | Baseline Laplacian | PoC |
|---|---|---|---|
| Recall@20 (tối đa đạt được = 20/28 = 0.714) | 0.429 | 0.571 | 0.714 |
| Precision@20 | 0.600 | 0.800 | 1.000 |
| Average precision (cả bảng xếp hạng) | 0.592 | 0.855 | 1.000 |
| Ảnh sạch bị đưa vào top-20 | 8 | 4 (cả 4 là cam_B) | 0 |
| Thời gian chạy 96 ảnh | 0.13 s | 0.33 s | 0.54 s (≈ 0.56 s / 100 ảnh) |

Trên split eval chưa có nhãn, chỉ so được hai hàng đợi: PoC gắn cờ 18/40 ảnh; top-20 của PoC và baseline trùng 16 ảnh; 4 ảnh chỉ PoC chọn (`img_01_3`, `img_05_3`, `img_13_2`, `img_23_1`), 4 ảnh chỉ baseline chọn (`img_03_0`, `img_03_2`, `img_06_3`, `img_15_0`). Chưa biết bên nào đúng cho tới khi có GT.

## 05 · Evaluation protocol

- **Công thức primary metric:** Defect Recall@B, đơn vị = ảnh, B = 20, trên split eval (xem `reports/metric_contract.md`).
- **Threshold / budget:** 4 ngưỡng + `SHARP_K` + `FLAG_AT` + `HOLD_FRACTION` ở đầu `src/pipeline.py`, chốt từ dev trước khi chạy PoC trên eval và **không đổi sau khi xem hàng đợi eval**.
- **Độ bất định:** eval chỉ 40 ảnh (khoảng 20 lỗi), nên recall thay đổi 5 điểm phần trăm mỗi ảnh; khi có GT báo Wilson 95% CI. Số trên dev không có CI vì ngưỡng đã chọn trên đó.
- **Lệnh evaluate:** `python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --run-name poc --out reports/metrics_poc.json` (cần `gt/`, do giảng viên chạy).
- **Hạn chế của protocol (nói thẳng):** (1) nhãn dev do chính nhóm gắn bằng mắt; (2) khi in bảng đặc trưng để chọn ngưỡng, bảng in luôn cả các dòng split eval nên nhóm đã thấy số đo (không có nhãn) của ảnh eval; ngưỡng chỉ dựa trên thống kê dev nhưng đây không phải held-out tuyệt đối sạch; (3) sau khi chốt ngưỡng có xem 1 ảnh eval (`img_03_2`) để phân tích failure case, không dùng để sửa ngưỡng.

## 06 · Result slices

Slice theo loại lỗi, trên dev (nhãn tự gắn, top-20 trong 56 ảnh):

| Slice | N lỗi | Baseline tìm thấy | PoC tìm thấy | Ghi chú |
|---|---|---|---|---|
| blur | 8 | 8 | 8 | Laplacian cũng bắt tốt |
| compression | 10 | 3 | 7 | 3 ảnh còn lại chưa vào top-20 chỉ vì hết budget (PoC cho cả 28 ảnh lỗi điểm cao hơn mọi ảnh sạch, AP = 1.0) |
| dark | 6 | 5 | 1 | cũng do hết budget: các lỗi điểm bão hoà ngang nhau nên thứ tự giữa chúng không có ý nghĩa; Recall@20 đã đạt trần 0.714 |
| glare | 4 | 0 | 4 | baseline xếp glare ở hạng 21–50/56 |

Slice theo camera (dev): baseline báo nhầm 4 ảnh sạch của cam_B (`img_00_0`, `img_09_0`, `img_12_0`, `img_21_0`; Laplacian 166–267, thấp hơn cam_A khoảng 4–6 lần); PoC không có báo nhầm nào.

- **Failure case 1 — cam_B bị baseline báo nhầm:** cam_B có quang học mềm, `lap_var` của ảnh sạch chỉ 167–267 so với 800–1600 của cam_A, nên một ngưỡng toàn cục xếp ảnh sạch cam_B lên trên ảnh nén/glare cam_A. Root cause: Laplacian phụ thuộc tương phản và độ sắc của ống kính. Cách vá trong PoC: chia cho phương sai độ sáng và dùng ngưỡng blur rất thấp (0.03; ảnh mờ thật ≤ 0.005, cam_B sạch ≥ 0.157).
- **Failure case 2 — PoC bỏ sót glare mờ ban đêm (`img_03_2`, `img_06_3`):** hai ảnh eval này có quầng sáng khuếch tán từ đèn pha (độ sáng trung bình 75–78 so với ~33 ở ảnh cùng cảnh), nhưng không có vùng bão hoà ≥ 235 đủ lớn nên detector glare của PoC cho điểm thấp (hạng 39 và 40/40), còn baseline đưa chúng vào top-20. Root cause: detector glare dựa vào blob bão hoà; quầng mờ không bão hoà. Chưa sửa vì sẽ là tune sau khi thấy eval; hướng cải tiến: đo chênh giữa độ sáng nền làm mịn và độ sáng toàn ảnh. Đây chỉ là nhận định bằng mắt trên một ảnh, chưa có GT xác nhận.
- **Failure case 3 — nguy cơ loại nhầm ảnh đêm:** dev chỉ có `img_18_0/1` là đêm sạch; chúng không bị gắn cờ (điểm dark 0.0) và `p99.5` của chúng (197–219) cách xa ngưỡng 118. Khoảng trống này chỉ kiểm trên 2 ảnh, nên rủi ro loại nhầm ảnh đêm vẫn còn.
- **Điểm yếu đã biết:** 18/40 ảnh eval bị gắn cờ (45%), 8 trong số đó là `compression`; vài ảnh đêm (`img_01_3`, `img_13_2`, `img_06_2`, `img_03_3`) bị gắn compression với điểm 0.81–0.99 và nhóm chưa xác minh bằng mắt từng ảnh; reviewer cần xem kỹ nhóm này.
- **Latency / compute:** 0.54 s cho 96 ảnh (≈ 5.6 ms/ảnh), CPU Intel64 Family 6 Model 154, Windows 11 (10.0.22000), Python 3.12.10.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` (B = 20, xếp theo `score` giảm dần, trong 40 ảnh eval) và `out/poc/contact_sheet.html` (mở bằng trình duyệt, có ảnh, loại lỗi gợi ý và nút Export CSV).
- **Override và audit log:** `review()` trong `src/pipeline.py` đọc `out/poc/review_queue_reviewed.csv`. `approve`, `skip`, `escalate` giữ quyết định của máy; `reject` = ảnh thực ra sạch (KEEP, score 0); `edit` + `override_value` ∈ {`KEEP`, `RECAPTURE`, `blur`, `dark`, `glare`, `compression`}. Mỗi quyết định ghi một dòng vào `out/poc/audit_log.jsonl` (thời điểm, người review, trước/sau, lý do).
- **Vòng review:** đã chạy một vòng trên 20 ảnh của hàng đợi, kết quả ở `reports/review_queue.csv` và `reports/audit_log.jsonl` (20 dòng). 17 ảnh `approve` (15 ảnh bị cờ có loại lỗi khớp với những gì nhìn thấy, và 2 ảnh KEEP `img_23_1`, `img_06_0` trông sạch), 3 ảnh `escalate` (`img_16_3`, `img_03_3`, `img_19_2`: điểm compression 0.65–0.85, nhìn thumbnail không khẳng định được). Không có override: `reject`/`edit` = 0, nên `decision.json` vẫn là HOLD 18/40.
- **Lưu ý trung thực về review:** vòng review này do trợ lý AI (Claude) thực hiện theo ủy quyền của Nguyễn Hoàn Thiện, đọc thumbnail 320×180 trong một lần xem, không phải reviewer người độc lập; tên reviewer trong log ghi rõ điều đó. 3 ảnh `escalate` cần người thật xem lại ảnh gốc trước khi nộp.
- **Decision policy + reason_code + owner:** `GO` / `ALL_KEEP`; `REWORK` / `RECAPTURE_FLAGGED_IMAGES`; `HOLD` / `SYSTEMIC_CAPTURE_DEFECTS` (≥ 40% ảnh bị cờ). Owner: Nguyễn Hoàn Thiện - reviewer. Kết quả sau review: `HOLD`, 18/40 = 45% bị gắn cờ (compression 8, blur 4, dark 4, glare 2).
- **Khi nào HOLD/REWORK thay vì tự động release:** bất kỳ ảnh nào bị gắn cờ thì không tự động release lô; ≥ 40% bị cờ thì dừng cả lô để kiểm chuỗi thu ảnh, dưới 40% thì chỉ chụp lại các ảnh bị cờ.

## 08 · Reproduce & tests

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m src.main --track t02 --pipeline src.t02_baseline --output out/baseline --run-name baseline --offline --seed 42
.venv/Scripts/python.exe -m src.main --config configs/lab.yaml --track t02 --output out/poc --run-name poc --offline --seed 42
.venv/Scripts/python.exe -m tools.dev_selfcheck out/baseline/ranked_review.csv out/poc/ranked_review.csv
.venv/Scripts/python.exe -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --run-name poc --out reports/metrics_poc.json   # cần gt/ của giảng viên
.venv/Scripts/python.exe -m pytest -q
```

- **Output của `pytest`:** `47 passed, 39 skipped` (skip chủ yếu do thiếu `gt/` hoặc dữ liệu tuỳ chọn). Trên máy này pytest cần `--basetemp=<thư mục khác>` vì thư mục tạm mặc định báo `PermissionError`.
- **Thay đổi test:** `tests/test_cli.py::test_template_pipeline_fails_clearly_not_silently` kiểm template chưa cài thì exit 3; vì `src/pipeline.py` nay cài T02 nên test chuyển sang track `t01` (chưa cài) để giữ nguyên ý nghĩa.
- **Máy / OS / Python:** Intel64 Family 6 Model 154, Windows 11 (10.0.22000), Python 3.12.10. Git sha khi chạy: `b0ce8bf` + thay đổi của nhóm; commit code `2c9fb26`.

## 09 · Limitations & ethics

- **Rủi ro pháp lý / PII / license:** dữ liệu synthetic của giảng viên, không có người hay biển số thật; không đưa dữ liệu thật vào repo.
- **Điều chưa biết:** chưa có Recall@B chính thức; số trên dev lạc quan vì ngưỡng chọn trên dev; 4 ngưỡng dựa trên 56 ảnh của 14 cảnh; glare mờ và ảnh đêm chưa kiểm đủ. Nếu scale 10× (ảnh thật nhiều điều kiện), blockiness phụ thuộc kích thước và chất lượng nén gốc nên cần hiệu chỉnh lại; pipeline thì tuyến tính theo số ảnh.
- **Không tuyên bố** "đạt GDPR / luật Việt Nam" từ checklist tự động; giả định cần DPO/legal xác nhận.
- **Kế hoạch cải tiến:** detector quầng sáng khuếch tán cho glare ban đêm; ngưỡng theo nhóm camera hoặc ROI (mốc +24h); kiểm 10 ảnh out-of-domain (ảnh thật nếu giảng viên cấp `data/real/`); reviewer thứ hai độc lập.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| Nguyễn Hoàn Thiện | Nguyễn Hoàn Thiện <26ai.thiennh@vinuni.edu.vn> | `src/pipeline.py`, `src/t02_baseline.py`, `tools/dev_selfcheck.py`, `configs/lab.yaml`, `reports/` | `2c9fb26` — feat(t02): Laplacian baseline and 4-detector raw QC triage PoC | Có |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa |
|---|---|---|
| `docs/tracks/T02.md` (trong repo) | 2026-11-15 | Đề bài T02: output contract, metric Recall@B, baseline Laplacian, failure mode night / glare cục bộ / cam_B |
| `docs/INSTRUCTOR_SETUP.md` (trong repo) | 2026-11-15 | Giải thích vì sao repo học viên không có GT và giảng viên chạy chấm chính thức |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo và tag cuối cùng trong báo cáo; input mẫu không chứa PII thật.
- [x] Có 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy. *(evaluate cần `gt/` của giảng viên)*
- [ ] Có baseline/PoC metrics, ≥1 failure case, reviewer evidence, decision log. *(có failure case, reviewer evidence, decision log; metrics chờ giảng viên vì thiếu GT)*
- [x] Có license/source provenance, data splits, seed, offline environment.
- [x] Mỗi thành viên có ≥1 commit thực chất (`2c9fb26`).
