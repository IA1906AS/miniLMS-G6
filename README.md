# miniLMS · Nhóm 6

Backend Flask và giao diện Home / Account bằng tiếng Việt, hỗ trợ desktop và điện thoại.

## Chạy cục bộ

Dùng Python 3.12 cho ứng dụng Flask (CI và cấu hình `uv` đều dùng 3.12).

```bash
cd /workspace/miniLMS-G6
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
export JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python migrate.py
.venv/bin/flask --app app:create_app run --host 0.0.0.0 --port 5000
```

Trước khi chạy `migrate.py`, tạo database PostgreSQL tên `minilms_g6` (hoặc tên khác trong `DB_NAME`) và cấu hình kết nối trong file `.env` ở thư mục gốc:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=minilms_g6
DB_USER=postgres
DB_PASSWORD=your_local_password
```

Có thể dùng `DATABASE_URL=postgresql://user:password@host:5432/database` thay cho các biến `DB_*`. `migrate.py` tạo bảng và nạp dữ liệu mẫu; ứng dụng kết nối qua pool PostgreSQL khi khởi động.

- `/home` (hoặc `/`): tổng quan khóa học và điểm cá nhân.
- `/account`: đăng nhập, xem email / mã tài khoản / vai trò, đăng xuất.
- Tài khoản dữ liệu mẫu: `chi.sv@lms.test`, mật khẩu `Lms@2026` (chỉ dùng phát triển; xem `seed.json` để biết các vai trò khác).
- Sinh viên chỉ thấy khóa học đã ghi danh; giảng viên chỉ thấy khóa học phụ trách; quản trị viên thấy tất cả khóa học.
- JWT chỉ giữ trong bộ nhớ trang, hết hạn sau thời gian do backend cấp. Điều hướng Home / Account giữ phiên; tải lại trang cần đăng nhập lại.
- Chưa có chức năng sửa hồ sơ, đặt lại mật khẩu hoặc đăng ký. Dữ liệu backend được lưu trong PostgreSQL; chạy `migrate.py` để tạo bảng và nạp dữ liệu mẫu.
- Font web có fallback sang font hệ thống khi ngoại tuyến.

## Kiểm thử

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```
