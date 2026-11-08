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
- `/account`: xem email / mã tài khoản / vai trò, đăng xuất.
- `/reports`: xem trước và xuất CSV bảng điểm theo khóa học; tối đa 2 lượt xuất đồng thời mỗi process.
- `POST /courses/<id>/quizzes/<qid>/attempts` và các endpoint kèm theo: lượt làm bài kiểm tra điều hành bằng máy trạng thái `IN_PROGRESS → SUBMITTED → GRADED` (module `app/attempt_sm.py`); chặn bỏ qua bước bắt đầu, sửa bài sau khi nộp, nộp sau hạn (`QUIZ_DEADLINE_MINUTES`, mặc định 120).
- Tài khoản dữ liệu mẫu: `chi.sv@lms.test`, mật khẩu `Lms@2026` (chỉ dùng phát triển; xem `seed.json` để biết các vai trò khác).
- Sinh viên chỉ thấy khóa học đã ghi danh; giảng viên chỉ thấy khóa học phụ trách; quản trị viên thấy tất cả khóa học.
- JWT được giữ trong sessionStorage của tab cho đến khi hết hạn hoặc đăng xuất; API kiểm tra token ở phía server.
- Đăng ký (`POST /auth/register`, trùng email bị từ chối) và đặt lại mật khẩu bằng OTP 8 số (`POST /auth/forgot-password` + `POST /auth/reset-password`, OTP có hiệu lực 5 phút; môi trường lab trả OTP trong response thay vì gửi email). Chưa có chức năng sửa hồ sơ.
- Font web có fallback sang font hệ thống khi ngoại tuyến.

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
