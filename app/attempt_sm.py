"""
attempt_sm.py – Máy trạng thái cho lượt làm bài kiểm tra (P7).

Mọi thay đổi trên một lượt làm bài đều phải đi qua bảng chuyển trạng
thái TRANSITIONS; tổ hợp (trạng thái, hành động) không có trong bảng
thì bị từ chối. Việc áp dụng được thực hiện atomically trong
store_pg.py (UPDATE ... WHERE state = %s) nên hai request chạy đua
cũng không đi xuyên được máy trạng thái.

Sơ đồ:
    IN_PROGRESS --SAVE--> IN_PROGRESS
    IN_PROGRESS --SUBMIT--> SUBMITTED
    SUBMITTED   --GRADE--> GRADED (trạng thái cuối)
"""

from .errors import InvalidAttemptState

IN_PROGRESS = "IN_PROGRESS"
SUBMITTED = "SUBMITTED"
GRADED = "GRADED"

# Hành động hợp lệ trên một lượt làm bài
SAVE = "SAVE"
SUBMIT = "SUBMIT"
GRADE = "GRADE"

# (trạng thái hiện tại, hành động) -> trạng thái sau
TRANSITIONS = {
    (IN_PROGRESS, SAVE): IN_PROGRESS,
    (IN_PROGRESS, SUBMIT): SUBMITTED,
    (SUBMITTED, GRADE): GRADED,
}


def transition(current, action):
    """Trả về trạng thái kế tiếp nếu hợp lệ, ngược lại ném InvalidAttemptState."""
    try:
        return TRANSITIONS[(current, action)]
    except KeyError:
        raise InvalidAttemptState(
            f"Hành động {action} không được phép ở trạng thái {current}"
        ) from None
