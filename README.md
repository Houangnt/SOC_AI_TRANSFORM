# SOC_AI_TRANSFORM

AI agent LifeMate với dashboard web, bộ skill nghiệp vụ, Gemini và SDK ToolEnv chính thức.

## Giao diện

![Giao diện Tổng quan SOC_AI_TRANSFORM với tông đen–đỏ](assets/ui-overview.png)

*Ảnh minh hoạ giao diện với dữ liệu demo.*

## Cài và chạy

```bash
git clone https://github.com/Houangnt/SOC_AI_TRANSFORM.git
cd SOC_AI_TRANSFORM
uv sync --frozen --python 3.12
```

Nếu nhận mã nguồn qua thư mục hoặc ZIP, mở terminal tại thư mục chứa `pyproject.toml`
và chạy lệnh `uv sync` ở trên.

Tạo `.env` từ mẫu nếu chưa có:

```bash
# macOS / Linux
cp -n .env.example .env
```

Windows PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Mở `.env`, điền Gemini API key của bạn vào `GEMINI_API_KEY=` và lưu lại.
Mẫu đã chọn sẵn cấu hình đã chạy thử trong dự án:

```dotenv
SOC_AI_TRANSFORM_PROVIDER=gemini
GEMINI_API_KEY=
SOC_AI_TRANSFORM_MODEL=gemini-3.1-flash-lite
SOC_AI_TRANSFORM_SMALL_MODEL=gemini-3.1-flash-lite
SOC_AI_TRANSFORM_LLM_TIMEOUT=45
```

Khởi động dashboard:

```bash
uv run --frozen SOC_AI_TRANSFORM dashboard
```

Mở **http://localhost:9000**. Nếu cổng bận, dùng URL được in trong terminal.
Nhấn `Ctrl+C` để dừng. Sau khi sửa `.env` hoặc cập nhật backend, khởi động lại.

## Thử bộ skill LifeMate trên UI

1. Mở **http://localhost:9000/#lifemate**. Đây là trang mở mặc định của dashboard.
2. Chọn **public_test** hoặc **train**, rồi chọn mã mẫu.
3. Kiểm tra hoặc sửa transcript trong ô **Yêu cầu cần thử**. Context và history lấy từ mẫu đã chọn.
4. Bấm **Chạy yêu cầu**. Xem skill được chọn, tham số và kết quả từng tool call.
5. Khi kết thúc, xem `state_hash` và bấm **Tải submission.jsonl** để lưu kết quả của mẫu.

Tab **Nghiệp vụ (50)** cho phép tìm và đọc 49 nghiệp vụ cùng 1 skill điều phối.
Tab **Thư viện tool** hiển thị schema chính thức và quyền dùng tool của mẫu đã chọn.
Ba skill demo cũ `weekly-brief`, `schedule-meeting`, `meeting-prep` đã được gỡ.
Khung chat demo được ẩn trên trang LifeMate; các trang phát triển khác vẫn giữ nguyên.

UI dùng SDK `zaic_tools` và runner thật của LifeMate. Mỗi lần bấm Chạy là một lượt suy luận
mới với một môi trường riêng; không tự chạy lại khi lỗi. Kết quả và log lưu tại
`.SOC_AI_TRANSFORM/lifemate/ui/`, ngoài Git. Chưa có điểm chấm tự động của BTC.

## Cấu trúc cần biết

| Đường dẫn | Vai trò |
|---|---|
| `SOC_AI_TRANSFORM/` | Agent, model adapters, tools, memory và dashboard |
| `SOC_AI_TRANSFORM/ops/static/` | Giao diện web |
| `SOC_AI_TRANSFORM/lifemate/` | Bộ nạp skill, runner và tích hợp UI LifeMate |
| `pyproject.toml`, `uv.lock` | Dependency và phiên bản cài đặt |
| `.env.example`, `.env` | Mẫu cấu hình và cấu hình local |
| `evals/`, `scripts/` | Kiểm tra và tiện ích phát triển |
| `sql/` | Schema cho backend Supabase tuỳ chọn |

## Phát triển

```bash
uv run --frozen --extra dev pytest -q evals/deterministic
uv run --frozen --extra dev ruff check SOC_AI_TRANSFORM evals scripts
```

Mặc định bộ deterministic chạy offline với model giả lập.

Dự án có runner LifeMate dùng transcript và SDK chính thức, chưa có evaluator điểm BTC.
Voice gateway là tính năng tuỳ chọn, cài bằng `uv sync --frozen --extra voice`.
ASR LifeMate dùng PhoWhisper medium + LoRA improved v2, cài bằng
`uv sync --frozen --extra asr` (độc lập với voice gateway).

## Audio → ASR → LifeMate trên dashboard

`evaluation_improved_v2` chứa `metrics.json` và `test_predictions.jsonl`, không chứa
trọng số. ASR trực tiếp dùng base `vinai/PhoWhisper-medium` tại revision
`55a7e3eb6c906de891f8f06a107754427dd3be79` và LoRA `step_00000080/adapter`.
Trọng số base tải từ Hugging Face ở lần chạy đầu; những lần sau dùng cache.

Với cấu trúc workspace gồm repo, `ASR_model`, `zl_dataset`, `skills` và `rules`,
đặt các dòng sau trong `.env` ở gốc repo:

```dotenv
SOC_AI_TRANSFORM_BUSINESS_SKILLS_ROOT=..
SOC_AI_TRANSFORM_LIFEMATE_DATA_ROOT=../zl_dataset/train+public_test
SOC_AI_TRANSFORM_ASR_EVALUATION_ROOT=../ASR_model/evaluation_improved_v2
SOC_AI_TRANSFORM_ASR_ADAPTER=models/phowhisper-medium-improved-v2/adapter
SOC_AI_TRANSFORM_ASR_DEVICE=auto
```

```powershell
uv sync --frozen --extra asr
uv run --frozen --extra asr SOC_AI_TRANSFORM dashboard
```

Trên trang **LifeMate → Chạy thử**:

1. Chọn split/mẫu. Để nói trực tiếp, bấm **Ghi âm bằng micro**, cho phép trình duyệt
   dùng micro, nói yêu cầu rồi bấm **Dừng & nhận dạng**. Bản ghi được chuyển thành WAV
   và tự gửi sang ASR local. Bạn có thể nghe lại bản ghi ngay trên trang.
   Micro tự dừng khi đạt giới hạn 120 giây / 16 MB; bấm **Huỷ ghi âm** để bỏ bản ghi.
   Rời trang LifeMate sẽ dừng micro. Cần trình duyệt hỗ trợ micro tại localhost hoặc HTTPS.
   Bản ghi thay câu hiện tại, context và history vẫn thuộc mẫu đã chọn.
2. Bấm **Chạy ASR từ audio**. Hệ thống nhận dạng cả câu hiện tại và audio user trong
   history bằng cùng checkpoint. Mỗi file tối đa 16 MB, 120 giây; audio dài được
   chia đoạn 30 giây. GPU CUDA được dùng nếu khả dụng, nếu không dùng CPU.
   Nút này dùng để nhận dạng lại bản ghi, audio của mẫu hoặc file WAV/FLAC/OGG bạn chọn.
3. Hoặc bấm **Dùng prediction có sẵn** để đọc `prediction` từ file đánh giá,
   không chạy model. Chỉ dùng được khi có đủ prediction cho câu hiện tại và history;
   tập đánh giá hiện có không bao phủ toàn bộ train/public_test.
4. Kiểm tra/sửa transcript rồi bấm **Chạy yêu cầu**. Transcript history từ ASR đi
   cùng lượt chạy; không thay bằng reference/nhãn hoặc transcript của lượt khác.

ASR chạy local, không cần Gemini key. Bước chạy agent vẫn cần API key của provider.
Không tự chạy agent sau ASR. File audio tải lên chỉ xử lý trong bộ nhớ của lượt ASR;
trọng số và dữ liệu đánh giá không được chép vào Git. API nhận dạng là
`POST /api/lifemate/asr`; nhận `split`, `sample_id`, `mode` (`live`/`saved`),
và tuỳ chọn `audio_base64` cho câu hiện tại. `/api/lifemate/run` nhận thêm
`asr_transcripts` từ kết quả nhận dạng để sử dụng đúng history.

## Skill nghiệp vụ LifeMate

Các tài nguyên do BTC cung cấp được giữ ngoài Git công khai. Sau khi nhận bộ dữ liệu
và bộ skill theo quyền của đội, thêm dòng này vào `.env` (sửa đường dẫn theo máy):

```dotenv
SOC_AI_TRANSFORM_BUSINESS_SKILLS_ROOT=../business_skills
```

Kiểm tra bộ skill và thử chọn nghiệp vụ:

```bash
uv run --frozen SOC_AI_TRANSFORM lifemate inspect
uv run --frozen SOC_AI_TRANSFORM lifemate route --text "Cập nhật số điện thoại của anh Nam"
```

`route` chỉ chọn nghiệp vụ, chưa thực thi tool. Runner dưới đây dùng transcript chuẩn
của train và SDK `zaic_tools` nằm sẵn trong split; không cần cài SDK bằng pip:

```bash
uv run --frozen SOC_AI_TRANSFORM lifemate run --data-root "../train+public_test" --split train --limit 1 --output .SOC_AI_TRANSFORM/lifemate/train-first.jsonl
```

Với public test, cung cấp transcript ASR cho cả câu hiện tại và các lượt user trong history:

```bash
uv run --frozen SOC_AI_TRANSFORM lifemate run --data-root "../train+public_test" --split public_test --ids public_0002 --transcripts ../transcripts.json --output .SOC_AI_TRANSFORM/lifemate/public-first.jsonl
```

Runner gửi transcript, context, history và kết quả tool tới API model đã cấu hình.
Mỗi mẫu chỉ tạo một `ToolEnv`, chỉ truy cập trạng thái qua API SDK, và xuất nguyên log
`env.get_tool_calls()` cùng `env.get_state_hash()`. Nếu có lỗi giữa chừng, log đã thực thi
được lưu trước khi dừng; không tự chạy lại từ đầu. File kết quả phải là file mới.
Đây là đường chạy thử nghiệm, chưa có evaluator điểm BTC. CLI nhận transcript;
dashboard hỗ trợ ASR trực tiếp từ audio như hướng dẫn phía trên.
Dashboard mặc định mở LifeMate và dùng chính runner này khi bấm Chạy.

## Harness và memory DB

UI và CLI LifeMate cùng chạy qua harness `SOC_AI_TRANSFORM`:
`for_lifemate(...)` nhận registry của mẫu và `respond_lifemate(...)` dùng vòng lặp,
model adapter, session và tracer hiện có.

SQLite `.SOC_AI_TRANSFORM/state.db` được giữ nguyên. Mỗi lượt LifeMate thêm lịch sử,
phản hồi, skill, tool calls và state_hash vào `chat_log` với source `lifemate`;
trace vẫn nằm trong `.SOC_AI_TRANSFORM/traces/`. Facts, episodes và lịch sử cũ được giữ.
Khi suy luận mẫu thi, chỉ context/history của mẫu được dùng; không tự truy hồi bộ nhớ
cá nhân hoặc dữ liệu của các lượt chạy khác, và không tự tổng hợp mẫu thi thành facts.

Trang **Thư viện tool** đọc chính catalog mà runner dùng: train có 147 tool,
public_test có 122 tool. Chọn mẫu để xem tool được phép; `sys.ask_missing_info`
luôn có sẵn. Bỏ bộ lọc để xem toàn catalog của split.

## Chat Tổng quan dùng LifeMate

Khung chat ở Tổng quan và các trang phát triển dùng cùng mẫu được chọn trên LifeMate.
Nút phía trên khung chat hiển thị split/mã mẫu và đưa về màn hình chọn mẫu.
Mỗi yêu cầu thực thi trong chat là một lượt thử mới, không nối trạng thái của các lượt
chạy trước vào môi trường mẫu. Memory DB vẫn lưu toàn bộ lịch sử.

Hỏi `Bạn có những tool nào?` để đọc trực tiếp danh sách tool được phép từ catalog BTC,
không cần gọi model. Yêu cầu thực thi đi qua cùng SDK/harness của trang LifeMate.
Khi chưa có mẫu phù hợp, chat yêu cầu chọn mẫu thay vì chạy tool demo.

Các tool local `create_event`, `list_events`, `save_note`, `send_message` đã được gỡ.
Các hàm probe/sync Google và Apple Calendar còn dùng bởi Connections được giữ riêng;
trạng thái lịch, ghi chú và outbox đã lưu không bị xoá.
