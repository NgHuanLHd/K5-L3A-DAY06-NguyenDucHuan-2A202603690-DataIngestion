# Báo cáo cá nhân — Day 06: Data Ingestion Engineering

| | |
|---|---|
| **Học viên** | Nguyễn Đức Huân — 2A202603690 — L3A |
| **Corpus** | World Bank, *Taking Stock* (Viet Nam Economic Update), số 08/2024 và 03/2025 |
| **Ngày chạy** | 13/11/2026 |
| **Repo** | https://github.com/NgHuanLHd/K5-L3A-DAY06-NguyenDucHuan-2A202603690-DataIngestion |

## Tóm tắt

- So sánh 3 cấu hình trên 94 trang nội dung và 23 câu hỏi (17 dev / 6 test).
- **Cấu hình chọn: C** (chunk theo đoạn + lọc theo năm báo cáo), theo tiêu chí chốt trước trên dev.
- Test: Evidence Hit@3 của B và C là 4/6, của A là 2/6.
- Chunk theo đoạn mạch lạc hơn rõ rệt: coherence 1,60/2 so với 0,90/2.
- Bộ lọc năm không tăng Hit@3 nhưng giữ kết quả đúng tài liệu (2/2 so với 0/2 trên test).

---

## 1. Dữ liệu và pipeline

### 1.1. Corpus

| Mã | Tài liệu | Trang PDF | Trang nội dung | Khoảng trang tính |
|---|---|---|---|---|
| `ts-2024-08` | Taking Stock 08/2024 — *Reaching New Heights in Capital Markets* | 64 | 46 | 13–18, 20–37, 39–60 |
| `ts-2025-03` | Taking Stock 03/2025 — *Electrifying Journeys* | 62 | 48 | 11–17, 19–40, 42–60 |
| | **Tổng** | 126 | **94** | |

- Nguồn: World Bank Open Knowledge Repository, bản tiếng Anh, truy cập 13/11/2026.
- Giấy phép: CC BY-NC 3.0 IGO.
- Quy tắc tính trang: số trang vật lý PDF. Loại bìa, mục lục, danh mục, lời cảm ơn, trang ngăn chương, bìa sau.
- Lý do chọn: hai báo cáo cùng loại, khác năm, nhiều chỉ số trùng tên nhưng khác giá trị.
- Chi tiết: [`data/manifest.json`](../../data/manifest.json).

### 1.2. Chuẩn hóa và lỗi

| Bước | Cách làm |
|---|---|
| Trích xuất | `pypdf` 6.21.4, theo từng trang |
| Chuẩn hóa | Unicode NFC, bỏ gạch nối mềm, nối từ bị ngắt dòng, gộp khoảng trắng |
| Kiểm soát | Trang < 50 ký tự được ghi log và loại |
| Kết quả | 94/94 trang hợp lệ, 0 lỗi, 240.933 ký tự |

Giới hạn:
- Chữ trong biểu đồ và bảng bị trích thành chuỗi số rời rạc.
- Chunk không vượt ranh giới trang.
- Không cần OCR.

### 1.3. Embedding và vector store

| Thành phần | Giá trị |
|---|---|
| Model | `intfloat/multilingual-e5-small` (local), 384 chiều, tối đa 512 token |
| Xử lý | Tiền tố `query: ` / `passage: `, vector chuẩn hóa |
| Thư viện | sentence-transformers 6.3.0, torch 2.15.0 (CPU) |
| Vector store | PostgreSQL 16 + pgvector 0.8 (Docker) |
| Độ đo | Cosine, tìm kiếm chính xác (không index) |
| Chi phí | 0 |

- Model ban đầu `paraphrase-multilingual-MiniLM-L12-v2` chỉ nhận 128 token, cắt 26% chunk A và 63% chunk B, nên bị thay.
- Với e5-small: 0 chunk vượt giới hạn.

### 1.4. Metadata

| Trường | Nguồn | Vai trò |
|---|---|---|
| `document_id`, `source`, `page` | Manifest, tên file, số trang PDF | Truy vết |
| `chunk_id` | Sinh theo tài liệu–trang–thứ tự | Chống trùng khi nạp lại |
| **`year`** | Năm trên bìa báo cáo | **Trường lọc** (2024 / 2025) |
| `document_type`, `language`, `title` | Manifest | Truy vết |

---

## 2. Cấu hình và benchmark

### 2.1. Cấu hình

| | Chunking | Lọc |
|---|---|---|
| **A** | Cố định 500 ký tự, overlap 50 | Không |
| **B** | Theo đoạn, tối đa 800 ký tự | Không |
| **C** | Như B (dùng chung index) | `year`, chỉ khi câu hỏi nêu năm báo cáo |

A–B chỉ khác chunking. B–C chỉ khác bộ lọc. Dữ liệu, model, câu hỏi và cách tính điểm giữ nguyên.

### 2.2. Benchmark

| Phân loại | Số câu |
|---|---|
| Dev / Test | 17 / 6 |
| Trực tiếp / Diễn đạt lại / Điều kiện / Có filter | 9 / 5 / 4 / 5 |
| Câu có filter | Dev: q05, q06, q17 · Test: q18, q19 |
| Theo tài liệu (2024 / 2025) | 12 / 11 |

- Viết và chia dev/test trước khi chạy thử.
- Evidence chép từ văn bản đã chuẩn hóa; 23/23 câu qua kiểm tra tự động.
- Năm lọc lấy từ câu hỏi, không lấy từ đáp án.
- Rủi ro rò rỉ: dev và test cùng nguồn, một số câu ở trang gần nhau (q17 trang 12, q18 trang 13).

### 2.3. Tiêu chí chọn (chốt trước khi chạy)

1. Evidence Hit@3 trên dev.
2. Hit@1 trên dev.
3. Ít chunk hơn.

Test chạy một lần sau khi chọn.

---

## 3. Kết quả

### 3.1. Truy xuất và tài nguyên

| Strategy | Split | Hit@1 | Evidence Hit@3 | Chunk | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 7/17 | 11/17 | 572 | nạp 32,0 s · 234 ms/câu¹ | 0 |
| B | dev | 6/17 | 11/17 | 422 | nạp 12,1 s · 47 ms/câu | 0 |
| C | dev | 7/17 | 11/17 | 422 | 38 ms/câu | 0 |
| A | test | 1/6 | 2/6 | 572 | 49 ms/câu | 0 |
| B | test | 3/6 | 4/6 | 422 | 32 ms/câu | 0 |
| **C** | **test** | **3/6** | **4/6** | 422 | 37 ms/câu | 0 |

¹ Gồm thời gian khởi động model.

- Nạp = tạo vector + ghi DB. A: 29,1 s + 3,0 s; B: 11,0 s + 1,2 s (laptop CPU).
- Nạp lại không tạo bản ghi trùng: A 572 → 572, B 422 → 422.
- Độ dài chunk trung bình: A 463 ký tự (52–500), B 570 ký tự (80–800).

### 3.2. Chọn cấu hình

| Bước | Dev | Kết quả |
|---|---|---|
| Hit@3 | A = B = C = 11/17 | Hòa |
| Hit@1 | A = C = 7/17 > B = 6/17 | Loại B |
| Số chunk | C 422 < A 572 | **Chọn C** |

### 3.3. Đánh giá thủ công

| Strategy | Coherence /2 (n=10) | Metadata đủ và đúng | Filter tuân thủ (test) | Grounding 0/1/2 · TB /2 (n=6) |
|---|---|---|---|---|
| A | 0,90 (0: 1 · 1: 9 · 2: 0) | 18/18 | 0/2 | 2/2/2 · 1,00 |
| B | 1,60 (0: 1 · 1: 2 · 2: 7) | 18/18 | 0/2 | 1/1/4 · 1,50 |
| C | 1,60 (dùng chung chunk B) | 18/18 | 2/2 | 1/1/4 · 1,50 |

- Filter tuân thủ trên dev: A 2/3, B 1/3, C 3/3.
- Metadata: 54/54 bản ghi đúng `source`, `page`, `year`.
  - Hữu ích: `chunk_id` và `page` cho phép mở đúng trang PDF; `year` loại kết quả sai báo cáo.
  - Hạn chế: không có trường `section`, nên không lọc được theo chương.
- Mẫu coherence: điểm giữa của 10 trang đầu (sắp theo tài liệu, trang), chọn trước khi chấm.
- Mẫu metadata/grounding: 6 câu test × top-3.
- Người chấm: tác giả. Coherence chấm trước khi xem Hit@3.

### 3.4. File kết quả

| Nội dung | File |
|---|---|
| Trace top-3 | `results/traces_dev.jsonl`, `results/traces_test.jsonl` |
| Chỉ số | `results/summary_dev.json`, `results/summary_test.json` |
| Thống kê nạp | `results/ingest_stats.json` |
| Nhãn thủ công | `results/audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv` |
| Văn bản đã chuẩn hóa | `results/pages.jsonl` |

---

## 4. Phân tích

### 4.1. A–B: chunking

- Dev hòa (Hit@3 11/17). Test B hơn A: 4/6 so với 2/6.
- Coherence B 1,60 so với A 0,90. Chunk A bị cắt giữa câu hoặc giữa từ ở 9/10 mẫu.
- Grounding B 1,50 so với A 1,00.
- B ít hơn 150 chunk và tạo vector nhanh hơn 2,6 lần.

**Ví dụ q21** (test, `ts-2025-03`, trang 53): A tìm đúng trang ở vị trí 1, nhưng chunk dừng ở "…If the grid". Con số "2.2 million tons CO2eq" nằm ở chunk sau. A trượt, B trúng ở vị trí 1.

### 4.2. B–C: bộ lọc năm

- Hit@3 không đổi: dev 11/17, test 4/6.
- Hit@1 dev: C 7/17, B 6/17.
- Filter tuân thủ: C 5/5, B 1/5 (dev + test).

**Ví dụ q17** (dev, retail sales theo báo cáo 2025): B xếp đầu chunk báo cáo 2024 (trang 22). C loại chunk này và đưa đáp án đúng (`ts-2025-03`, trang 12) lên vị trí 1.

**Ví dụ q18** (test, mức mất giá VND, `ts-2025-03` trang 13): C lọc đúng năm nhưng vẫn trượt. Vị trí 1 là dữ liệu biểu đồ Figure 1.22 (trang 30). Câu chứa "4.4 percent" không vào top-3. Grounding = 0 ở cả ba cấu hình.

### 4.3. Nhóm lỗi khác

| Nhóm | Câu | Mô tả |
|---|---|---|
| Nhiễu biểu đồ | q20 | Lấy đúng trang 45 nhưng là chú thích Figure 2.3, thiếu mốc 2035 |
| Diễn đạt khác nguồn | q02, q07 | "untracked money" / "unrecorded capital outflows"; "pension funds, insurers…" / "institutional investors". Cả ba trượt |
| Thiếu ngữ cảnh năm | q01 | Không có filter; B lấy số liệu cả năm 2024 từ báo cáo 2025 |

### 4.4. Kết luận

- Chọn **C**. Kết quả test nhất quán với lựa chọn trên dev.
- Chunk theo đoạn là thay đổi có tác động lớn nhất (Hit@3 test, coherence, grounding).
- Bộ lọc năm cải thiện độ chính xác về nguồn và thứ hạng, không tăng độ phủ.
- Điều kiện áp dụng: C chỉ có ích khi người dùng cung cấp năm báo cáo. Năm sai sẽ loại mất đáp án đúng.
- Phù hợp với kho tài liệu có nhiều phiên bản theo năm. Không cần thiết với kho một phiên bản.

---

## 5. Hạn chế

- Test 6 câu: mỗi câu tương đương ~17%. Chưa đủ để kết luận chắc chắn.
- Hit@3 dev 11/17: khoảng 1/3 câu không cấu hình nào tìm được.
- Hit yêu cầu một chunk chứa nguyên văn evidence; bất lợi cho A khi evidence bị chia đôi.
- Nhãn thủ công do một người chấm.
- Thời gian đo một lần trên CPU.
- Kết luận chỉ áp dụng cho corpus này.

## 6. Hướng cải tiến

- Cho phép chunk nối sang trang kế tiếp.
- Tách văn bản biểu đồ, bảng khỏi văn bản chính.
- Thêm trường `section` để lọc theo chương.
- Kết hợp BM25 với tìm kiếm ngữ nghĩa cho câu diễn đạt khác nguồn.
- Mở rộng test, thêm người chấm thứ hai.

## 7. Sử dụng AI

| Hạng mục | Công cụ / vai trò |
|---|---|
| Lập kế hoạch, tìm tài liệu, manifest | Claude Code hỗ trợ |
| Code `starter/src/` | Claude Code viết; học viên đọc, chạy và kiểm tra |
| Benchmark, nhãn chấm tay | Học viên tự thực hiện |
| Báo cáo | Claude Code soạn nháp từ kết quả thật; học viên rà soát |

Kiểm chứng: chạy toàn bộ pipeline, đối chiếu evidence với PDF gốc, đọc lại code. Mọi số liệu lấy từ `results/` của lần chạy ngày 13/11/2026.
