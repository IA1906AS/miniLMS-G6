"""Kiểm tra máy trạng thái cho lượt làm bài kiểm tra (P7, bản sau khi sửa).

Chạy từ thư mục gốc sau khi đã khởi tạo và nạp dữ liệu mẫu:
    python db_init.py && python db_seed.py
    uv run --no-sync --python 3.12 python scripts/check_state_machine.py

Ba lỗi từng xảy ra ở bản trước (tag p7-before) đều bị chặn:
    1. Bỏ qua bước: nộp khi chưa bắt đầu      -> 404 NOT_FOUND
    2. Sửa bài đã nộp                          -> 409 INVALID_ATTEMPT_STATE
    3. Nộp sau hạn                             -> 409 DEADLINE_PASSED
Kèm luồng hợp lệ start -> save -> submit -> grade và chặn thao tác sau GRADED.
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.auth import create_token  # noqa: E402


def main():
    with TemporaryDirectory() as directory:
        app = create_app({
            "JWT_SECRET": "p7-state-machine-local-only-secret-32-ch",
            "AUDIT_LOG_PATH": str(Path(directory) / "audit.log"),
        })
        with app.app_context():
            chi = {"Authorization": f"Bearer {create_token('u4')}"}
            dung = {"Authorization": f"Bearer {create_token('u5')}"}
            em = {"Authorization": f"Bearer {create_token('u6')}"}
            an = {"Authorization": f"Bearer {create_token('u2')}"}

        client = app.test_client()
        blocked = []

        # 1. Bỏ qua bước bắt đầu -> bị chặn, không tạo lượt "ma"
        resp = client.post(
            "/courses/c1/quizzes/q9/attempts/submit",
            headers=chi,
            json={"answers": "A,B,C"},
        )
        ok = resp.status_code == 404 and resp.json["error"] == "NOT_FOUND"
        blocked.append(ok)
        print(f"1. Nộp khi chưa bắt đầu      -> HTTP {resp.status_code} "
              f"{resp.json.get('error')}  {'(chặn)' if ok else '(LỖI: chưa chặn!)'}")

        # 2. Sửa bài đã nộp -> bị chặn
        resp = client.put(
            "/courses/c1/quizzes/q1/attempts/answers",
            headers=dung,
            json={"answers": "đáp án mới sau khi nộp"},
        )
        ok = resp.status_code == 409 and resp.json["error"] == "INVALID_ATTEMPT_STATE"
        blocked.append(ok)
        print(f"2. Sửa bài đã nộp            -> HTTP {resp.status_code} "
              f"{resp.json.get('error')}  {'(chặn)' if ok else '(LỖI: chưa chặn!)'}")

        # 3. Nộp sau hạn -> bị chặn
        resp = client.post(
            "/courses/c2/quizzes/q1/attempts/submit",
            headers=em,
            json={"answers": "A,C,B"},
        )
        ok = resp.status_code == 409 and resp.json["error"] == "DEADLINE_PASSED"
        blocked.append(ok)
        print(f"3. Nộp sau hạn               -> HTTP {resp.status_code} "
              f"{resp.json.get('error')}  {'(chặn)' if ok else '(LỖI: chưa chặn!)'}")

        # Luồng hợp lệ: start -> save -> submit -> grade
        resp = client.post("/courses/c1/quizzes/q2/attempts", headers=chi)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        print(f"4. Bắt đầu làm bài           -> HTTP 201 state={resp.json['state']}")
        resp = client.put(
            "/courses/c1/quizzes/q2/attempts/answers",
            headers=chi,
            json={"answers": "A,B"},
        )
        assert resp.status_code == 200
        print(f"   Lưu câu trả lời           -> HTTP 200 state={resp.json['state']}")
        resp = client.post(
            "/courses/c1/quizzes/q2/attempts/submit",
            headers=chi,
            json={"answers": "A,C"},
        )
        assert resp.status_code == 200
        print(f"   Nộp bài (trước hạn)       -> HTTP 200 state={resp.json['state']}")
        resp = client.post(
            "/courses/c1/quizzes/q2/attempts/u4/grade",
            headers=an,
            json={"score": 8.5},
        )
        assert resp.status_code == 200
        print(f"   Giảng viên chấm           -> HTTP 200 state={resp.json['state']} "
              f"score={resp.json['score']}")

        # GRADED là trạng thái cuối: chấm lại / sửa / nộp lại đều bị chặn
        resp = client.post(
            "/courses/c1/quizzes/q2/attempts/u4/grade",
            headers=an,
            json={"score": 10},
        )
        ok = resp.status_code == 409 and resp.json["error"] == "INVALID_ATTEMPT_STATE"
        blocked.append(ok)
        print(f"5. Thao tác sau khi GRADED   -> HTTP {resp.status_code} "
              f"{resp.json.get('error')}  {'(chặn)' if ok else '(LỖI: chưa chặn!)'}")

        print()
        if all(blocked):
            print("KẾT LUẬN (bản sau): 3 triệu chứng cũ đã bị chặn hết — "
                  "máy trạng thái hoạt động đúng.")
        else:
            print("KẾT LUẬN: có triệu chứng chưa được chặn — kiểm tra lại.")
            sys.exit(1)


if __name__ == "__main__":
    main()
