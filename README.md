# miniLMS · Nhóm 6

Backend Flask và giao diện Login / Home / Account / Reports bằng tiếng Việt, hỗ trợ desktop và điện thoại.

## Chạy cục bộ

Dùng Python 3.12 cho ứng dụng Flask (CI và cấu hình `uv` đều dùng 3.12).

Trên Windows (PowerShell), từ thư mục gốc project:

```powershell
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
uv run --python 3.12 python db_init.py
uv run --python 3.12 python db_seed.py
uv run --python 3.12 flask --app app:create_app run --host 127.0.0.1 --port 5000
```

Mở http://127.0.0.1:5000/ để đến trang đăng nhập.

Trên Linux/macOS:

```bash
cd /workspace/miniLMS-G6
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
export JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python db_init.py
.venv/bin/python db_seed.py
.venv/bin/flask --app app:create_app run --host 0.0.0.0 --port 5000
```

Trước khi chạy `db_init.py`, tạo database PostgreSQL tên `minilms_g6` (hoặc tên khác trong `DB_NAME`) và cấu hình kết nối trong file `.env` ở thư mục gốc:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=minilms_g6
DB_USER=postgres
DB_PASSWORD=your_local_password
```

Có thể dùng `DATABASE_URL=postgresql://user:password@host:5432/database` thay cho các biến `DB_*`. `db_init.py` tạo bảng, `db_seed.py` nạp dữ liệu mẫu; ứng dụng kết nối qua pool PostgreSQL khi khởi động.

- `/` (hoặc `/home`): chuyển đến `/login` nếu chưa đăng nhập; sau đăng nhập hiển thị khóa học và điểm cá nhân.
- `/login`: đăng nhập; `/register`: đăng ký tài khoản.
- `/account`: hồ sơ cá nhân (sửa họ tên/điện thoại/tiểu sử, ảnh đại diện), đổi mật khẩu, đăng xuất.
- `/courses`: tra cứu / ghi danh / tạo khóa học; `/course`: trang chi tiết gồm tài liệu, bài tập, bài kiểm tra, diễn đàn, thông báo, thành viên.
- `/reports`: xem trước và xuất CSV bảng điểm theo khóa học; tối đa 2 lượt xuất đồng thời mỗi process.
- `/admin` (chỉ ADMIN): quản trị người dùng (vai trò, khóa tài khoản), gỡ khóa học, xem nhật ký hoạt động.
- Tài khoản dữ liệu mẫu: `chi.sv@lms.test`, mật khẩu `Lms@2026` (chỉ dùng phát triển; xem `seed.json` để biết các vai trò khác).
- Sinh viên chỉ thấy khóa học đã ghi danh; giảng viên chỉ thấy khóa học phụ trách; quản trị viên thấy tất cả khóa học.
- JWT được giữ trong sessionStorage của tab cho đến khi hết hạn hoặc đăng xuất; API kiểm tra token ở phía server (đăng xuất thu hồi token qua jti).
- Font web có fallback sang font hệ thống khi ngoại tuyến.

## Tính năng theo đặc tả → API

Tài liệu đầy đủ (không cần mạng): `GET /api/openapi.yaml`, hoặc mở file `openapi.yaml` ở thư mục gốc.

| Nhóm đặc tả | Endpoint chính |
|---|---|
| 1. Đăng nhập / đăng ký / OTP | `POST /auth/login`, `POST /auth/register`, `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/change-password`, `POST /auth/logout` |
| 2. Hồ sơ cá nhân | `GET/PUT /me`, `POST /me/avatar`, `GET /files/avatars/<name>`, `GET /members?courseId=` |
| 3. Khóa học & ghi danh | `GET /api/courses?q=&instructorId=`, `POST /courses`, `PATCH /courses/<cid>`, `POST /courses/enroll`, `POST /courses/<cid>/students` |
| 4. Tài liệu bài giảng | `POST/GET /courses/<cid>/materials`, `GET /materials/<mid>/download`, `DELETE /materials/<mid>` |
| 5. Bài tập & bài nộp | `POST/GET /courses/<cid>/assignments`, `POST/GET /courses/<cid>/assignments/<aid>/submissions`, `GET /assignments/submissions/<sid>/download`, `POST /courses/<cid>/assignments/<aid>/submissions/<sid>/grade` |
| 6. Bài kiểm tra (máy trạng thái + chấm tự động) | `POST/GET /courses/<cid>/quizzes[/<qid>]`, `POST/GET /courses/<cid>/quizzes/<qid>/attempts`, `PUT .../attempts/answers`, `POST .../attempts/submit`, `POST .../attempts/<sid>/grade` |
| 7. Diễn đàn & thông báo | `POST/GET /courses/<cid>/topics`, `GET/PUT/DELETE /topics/<tid>`, `POST/GET /topics/<tid>/comments`, `PUT/DELETE /comments/<cid>`, `POST/GET /courses/<cid>/announcements` |
| 8. Quản trị & nhật ký | `GET /admin/users?q=`, `PATCH /admin/users/<uid>`, `DELETE /admin/courses/<cid>`, `GET /admin/audit` |
| Bảng điểm (P4–P6) | `GET/PUT /courses/<cid>/grades[/<sid>]`, `GET /courses/<cid>/grades/export` |

Ghi chú: đặt lại mật khẩu dùng OTP 8 số, hiệu lực 5 phút; môi trường lab trả OTP trong response thay vì gửi email (thông báo khóa học cũng vậy — `emailQueued: true`). Lượt làm bài kiểm tra điều hành bằng máy trạng thái `IN_PROGRESS → SUBMITTED → GRADED` (module `app/attempt_sm.py`); chặn bỏ qua bước bắt đầu, sửa bài sau khi nộp, nộp sau hạn (`QUIZ_DEADLINE_MINUTES`, mặc định 120). Khi nộp, hệ thống chấm tự động theo đáp án (sinh viên không thấy đáp án) và giữ trạng thái SUBMITTED để giảng viên xác nhận/điều chỉnh. Sửa/xóa chủ đề và bình luận chỉ dành cho tác giả. Tệp tải lên nằm trong `uploads/` (đã gitignore), giới hạn 10 MB chung / 2 MB ảnh đại diện, phần mở rộng được kiểm duyệt.

## Kiểm thử

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

Kiểm thử Bulkhead độc lập trên Windows (PowerShell), cần PostgreSQL đã khởi tạo và nạp dữ liệu mẫu; không cần chạy web server trước:

```powershell
uv run --python 3.12 python scripts/check_bulkhead.py
```

Kiểm thử máy trạng thái P7 (lượt làm bài kiểm tra), cùng điều kiện như trên:

```powershell
uv run --python 3.12 python scripts/check_state_machine.py
```

Kết quả mong đợi: nộp khi chưa bắt đầu → `404`, sửa bài đã nộp → `409 INVALID_ATTEMPT_STATE`, nộp sau hạn → `409 DEADLINE_PASSED`, luồng hợp lệ start → save → submit → grade trả `200/201`.

Bản "trước khi sửa" (chưa có máy trạng thái, tái hiện 3 triệu chứng trên) được lưu ở tag `p7-before`; bản "sau khi sửa" là commit hiện tại (tag `p7-after`). So sánh hai bản:

```bash
git diff p7-before p7-after -- app/attempt_sm.py app/services.py app/store_pg.py
```

## Retry với exponential backoff + jitter

Các thao tác tạo pool và lấy connection PostgreSQL được retry khi gặp lỗi tạm
thời (`OperationalError`, `InterfaceError`, pool tạm cạn) bằng exponential
backoff kèm full jitter, cài đặt trong `app/retry.py` và áp dụng ở `app/db.py`:

- Lần retry thứ `n` có trần delay `min(DB_RETRY_MAX_DELAY_MS, DB_RETRY_BASE_DELAY_MS * 2**(n-1))`;
  delay thực tế là ngẫu nhiên trong `[0, trần]` để nhiều request không retry
  cùng lúc (tránh "thundering herd").
- Retry áp dụng cho lúc tạo pool (database khởi động chậm) và lúc checkout
  connection (pool tạm cạn). Câu lệnh/transaction đã chạy bên trong `get_conn()`
  **không** retry tự động để tránh ghi dữ liệu hai lần.
- Mỗi lần retry ghi log WARNING dạng `DB connect/checkout failed (1/4): ...; retrying in ...`.

Cấu hình trong `.env` (giá trị mặc định trong ngoặc):

| Biến | Ý nghĩa | Mặc định |
|---|---|---|
| `DB_RETRY_ATTEMPTS` | Tổng số lần thử | `4` |
| `DB_RETRY_BASE_DELAY_MS` | Trần delay của lần retry đầu (ms) | `100` |
| `DB_RETRY_MAX_DELAY_MS` | Trần delay tối đa (ms) | `2000` |

Kiểm chứng nhanh, không cần PostgreSQL:

```powershell
uv run --python 3.12 python scripts/check_retry.py
```

Kết quả mong đợi: delay tăng `0.2 → 0.4 → 0.8 → 1.0s` khi tắt jitter; jitter luôn
nằm trong trần; retry dừng đúng số lần và ném lại lỗi cuối; `get_conn` retry
checkout rồi commit và trả connection về pool.
