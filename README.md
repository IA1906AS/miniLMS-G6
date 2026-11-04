# miniLMS · Nhóm 6

Backend Flask và giao diện Login / Home / Account / Reports bằng tiếng Việt, hỗ trợ desktop và điện thoại.

## Chạy cục bộ

Dùng Python 3.11+ cho ứng dụng Flask (CI dùng 3.11; cấu hình `uv` của kho mã yêu cầu 3.14).

Trên Windows (PowerShell), từ thư mục gốc project:

```powershell
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
uv run --no-sync --python 3.14 flask --app app:create_app run --host 127.0.0.1 --port 5000
```

Mở http://127.0.0.1:5000/ để đến trang đăng nhập.

Trên Linux/macOS:

```bash
cd /workspace/miniLMS-G6
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
export JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/flask --app app:create_app run --host 0.0.0.0 --port 5000
```

- `/` (hoặc `/home`): chuyển đến `/login` nếu chưa đăng nhập; sau đăng nhập hiển thị khóa học và điểm cá nhân.
- `/login`: đăng nhập; `/register`: đăng ký tài khoản.
- `/account`: xem email / mã tài khoản / vai trò, đăng xuất.
- `/reports`: xem trước và xuất CSV bảng điểm theo khóa học (mở từ trang chủ), tối đa 2 lượt xuất đồng thời mỗi process.
- Tài khoản dữ liệu mẫu: `chi.sv@lms.test`, mật khẩu `Lms@2026` (chỉ dùng phát triển; xem `seed.json` để biết các vai trò khác).
- Sinh viên chỉ thấy khóa học đã ghi danh; giảng viên chỉ thấy khóa học phụ trách; quản trị viên thấy tất cả khóa học.
- JWT được giữ trong sessionStorage của tab cho đến khi hết hạn hoặc đăng xuất; API kiểm tra token ở phía server. Tải lại trang trong cùng tab vẫn giữ phiên.
- Chưa có chức năng sửa hồ sơ hoặc đặt lại mật khẩu. Dữ liệu backend hiện giữ trong bộ nhớ và tải lại từ seed khi khởi động.
- Font web có fallback sang font hệ thống khi ngoại tuyến.

## Kiểm thử

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

Kiểm thử Bulkhead độc lập trên Windows (PowerShell), không cần chạy server trước:

```powershell
uv run --no-sync --python 3.14 python scripts/check_bulkhead.py
```
