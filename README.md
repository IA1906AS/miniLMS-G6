# miniLMS · Nhóm 6

Backend Flask và giao diện Home / Account bằng tiếng Việt, hỗ trợ desktop và điện thoại.

## Chạy cục bộ

Dùng Python 3.11+ cho ứng dụng Flask (CI dùng 3.11; cấu hình `uv` của kho mã yêu cầu 3.14).

```bash
cd /workspace/miniLMS-G6
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
export JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/flask --app app:create_app run --host 0.0.0.0 --port 5000
```

- `/home` (hoặc `/`): tổng quan khóa học và điểm cá nhân.
- `/account`: đăng nhập, xem email / mã tài khoản / vai trò, đăng xuất.
- Tài khoản dữ liệu mẫu: `chi.sv@lms.test`, mật khẩu `Lms@2026` (chỉ dùng phát triển; xem `seed.json` để biết các vai trò khác).
- Sinh viên chỉ thấy khóa học đã ghi danh; giảng viên chỉ thấy khóa học phụ trách; quản trị viên thấy tất cả khóa học.
- JWT chỉ giữ trong bộ nhớ trang, hết hạn sau thời gian do backend cấp. Điều hướng Home / Account giữ phiên; tải lại trang cần đăng nhập lại.
- Chưa có chức năng sửa hồ sơ, đặt lại mật khẩu hoặc đăng ký. Dữ liệu backend hiện giữ trong bộ nhớ và tải lại từ seed khi khởi động.
- Font web có fallback sang font hệ thống khi ngoại tuyến.

## Kiểm thử

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```
