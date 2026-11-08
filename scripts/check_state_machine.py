"""Demo triệu chứng của lượt làm bài kiểm tra CHƯA có máy trạng thái (P7, bản trước).

Chạy từ thư mục gốc sau khi đã khởi tạo và nạp dữ liệu mẫu:
    python db_init.py && python db_seed.py
    uv run --no-sync --python 3.12 python scripts/check_state_machine.py

Ba triệu chứng được tái hiện trên dữ liệu mẫu:
    1. Bỏ qua bước: nộp bài mà chưa từng bắt đầu -> vẫn được chấp nhận.
    2. Sửa bài đã nộp: lưu lại câu trả lời sau khi SUBMITTED -> vẫn được chấp nhận.
    3. Nộp sau hạn: deadline đã qua -> vẫn được chấp nhận.
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

        client = app.test_client()
        symptoms = []

        # 1. Bỏ qua bước bắt đầu: u4 nộp quiz q9 mà chưa bao giờ bấm "bắt đầu"
        resp = client.post(
            "/courses/c1/quizzes/q9/attempts/submit",
            headers=chi,
            json={"answers": "A,B,C"},
        )
        accepted = resp.status_code == 200 and resp.json["state"] == "SUBMITTED"
        symptoms.append(accepted)
        print(f"1. Nộp khi chưa bắt đầu      -> HTTP {resp.status_code} "
              f"state={resp.json.get('state')}")
        print("   TRIỆU CHỨNG: lượt làm bài được tạo thẳng ở trạng thái SUBMITTED, "
              "bỏ qua bước làm bài.")

        # 2. Sửa bài đã nộp: u5 đã SUBMITTED (a2) vẫn sửa được câu trả lời
        resp = client.put(
            "/courses/c1/quizzes/q1/attempts/answers",
            headers=dung,
            json={"answers": "đáp án mới sau khi nộp"},
        )
        accepted = (
            resp.status_code == 200
            and resp.json["answers"] == "đáp án mới sau khi nộp"
        )
        symptoms.append(accepted)
        print(f"2. Sửa bài đã nộp            -> HTTP {resp.status_code} "
              f"answers={resp.json.get('answers')!r}")
        print("   TRIỆU CHỨNG: bài đã SUBMITTED vẫn bị sửa đổi tuỳ ý.")

        # 3. Nộp sau hạn: u6 có lượt IN_PROGRESS nhưng deadline đã qua 1 tiếng
        resp = client.post(
            "/courses/c2/quizzes/q1/attempts/submit",
            headers=em,
            json={"answers": "A,C,B"},
        )
        accepted = resp.status_code == 200 and resp.json["state"] == "SUBMITTED"
        symptoms.append(accepted)
        print(f"3. Nộp sau hạn               -> HTTP {resp.status_code} "
              f"state={resp.json.get('state')}")
        print("   TRIỆU CHỨNG: nộp sau deadline vẫn được ghi nhận là SUBMITTED.")

        print()
        if all(symptoms):
            print("KẾT LUẬN (bản trước): 3/3 triệu chứng tái hiện — "
                  "thiếu máy trạng thái.")
        else:
            missing = 3 - sum(symptoms)
            print(f"KẾT LUẬN: {missing} triệu chứng KHÔNG tái hiện — kiểm tra lại seed.")
            sys.exit(1)


if __name__ == "__main__":
    main()
