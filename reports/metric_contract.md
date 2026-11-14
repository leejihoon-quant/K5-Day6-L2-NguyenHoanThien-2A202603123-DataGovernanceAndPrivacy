# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T02 · Raw QC Triage |
| Primary metric (tên đúng như evaluator in ra) | `Defect Recall@B` (kèm `Precision@B`) |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá | image (96 ảnh synthetic 320×180; eval = 40 ảnh) |
| Công thức + numerator / denominator | #ảnh lỗi thật nằm trong top-B của split eval / #ảnh lỗi thật của split eval |
| Cách ghép prediction ↔ GT | theo `image_id`; `ranked_review.csv` sắp theo `score` giảm dần |
| Candidate pool cố định | 40 ảnh `split == eval` của `fixtures/t02_raw_qc/images.csv` (baseline và PoC dùng chung) |
| Review budget B / K | B = 20 (`configs/tracks/t02.yaml`) |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Mỗi detector có 1 ngưỡng, đặt ở khoảng giữa hai nhóm trên split **dev** (ảnh tự gắn nhãn bằng mắt, `reports/dev_labels.csv`): blur `lap_norm` 0.03 · dark `p99.5` 118 · glare blob ≥235 = 180 px · compression `blockiness` 1.65. Hằng số ở đầu `src/pipeline.py`. Không dùng nhãn eval. |
| Eval split (không dùng để tune) | `eval` |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | miss = ảnh lỗi nằm ngoài top-B; false alarm = ảnh sạch trong top-B, báo theo slice `light` (`False alarm in top-B`) |
| Slices sẽ báo cáo (≥2) | `light` = day / dusk / night; `camera_id` = cam_A / cam_B (soft optics); loại lỗi blur / dark / glare / compression |
| Cách báo độ bất định khi N nhỏ | N eval = 40 → báo Wilson 95% CI cho recall khi có GT (chỉ giảng viên có `gt/`); dev chỉ có 56 ảnh tự gắn nhãn nên chỉ báo số thô |
| Ngày giờ chốt + người chốt | 2026-11-15 · Nguyễn Hoàn Thiện (ngưỡng chốt trước khi chạy PoC trên eval; không đổi sau đó) |

Baseline = Laplacian toàn ảnh, một ngưỡng (`src/t02_baseline.py`); baseline phụ = random (`src/examples/random_baseline.py`).
Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
