"""
retry.py – Exponential backoff with full jitter.

Công thức (AWS Architecture Blog, "Exponential Backoff and Jitter"):

    delay = random_uniform(0, min(max_delay, base_delay * 2 ** (retry - 1)))

Jitter toàn phần (full jitter) làm lệch thời điểm retry giữa các client, tránh
hiện tượng "thundering herd" khi một dependency vừa hồi phục. Tham số ``rand``
có thể được truyền vào để kiểm thử tất định.

Ví dụ:
    from app.retry import RetryPolicy, retry_call

    policy = RetryPolicy(attempts=4, base_delay=0.1, max_delay=2.0)
    row = retry_call(
        lambda: store.get_user_by_id(uid),
        policy=policy,
        retry_on=(psycopg2.OperationalError,),
    )
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import TypeVar

T = TypeVar("T")

# 2 ** 62 vẫn nằm gọn trong float; chặn số mũ để tránh tính toán vô ích khi
# attempts rất lớn (max_delay đã chặn kết quả trước đó).
_MAX_EXPONENT = 62


@dataclass(frozen=True)
class RetryPolicy:
    """Cấu hình số lần thử và độ trễ backoff.

    Args:
        attempts: Tổng số lần thực hiện (>= 1). ``attempts=1`` nghĩa là không retry.
        base_delay: Độ trễ cơ sở (giây) cho lần retry đầu tiên.
        max_delay: Trần độ trễ (giây) sau khi nhân đôi.
        jitter: Bật full jitter (mặc định). Tắt để có độ trễ tất định.
    """

    attempts: int = 4
    base_delay: float = 0.1
    max_delay: float = 2.0
    jitter: bool = True

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.base_delay < 0:
            raise ValueError("base_delay must be >= 0")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")

    def delay_for(
        self,
        retry: int,
        *,
        rand: Callable[[], float] = random.random,
    ) -> float:
        """Trả về độ trễ trước lần thử lại thứ ``retry`` (1-based)."""
        if retry < 1:
            raise ValueError("retry must be at least 1")
        if self.max_delay == 0:
            return 0.0

        exponent = min(retry - 1, _MAX_EXPONENT)
        cap = min(self.max_delay, self.base_delay * (2.0**exponent))
        return rand() * cap if self.jitter else cap


def _matches(exc: BaseException, retry_on: object) -> bool:
    """Kiểm tra exception có thuộc loại được phép retry hay không."""
    if isinstance(retry_on, tuple):
        return isinstance(exc, retry_on)
    if isinstance(retry_on, type) and issubclass(retry_on, BaseException):
        return isinstance(exc, retry_on)
    if callable(retry_on):
        return bool(retry_on(exc))
    return False


def retry_call(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    retry_on: type[BaseException] | tuple[type[BaseException], ...] | Callable[[BaseException], bool] = (
        Exception,
    ),
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
) -> T:
    """Gọi ``fn`` và retry khi gặp exception được chọn.

    Args:
        fn: Hàm không tham số cần thực hiện.
        policy: Cấu hình retry; mặc định ``RetryPolicy()``.
        retry_on: Kiểu exception (hoặc tuple kiểu, hoặc predicate nhận exception)
            được phép retry. Các exception khác được ném lại ngay lập tức.
        sleep: Hàm ngủ, mặc định ``time.sleep``; có thể thay bằng hàm ghi nhận
            trong kiểm thử.
        rand: Hàm trả về số thực trong [0, 1) dùng cho full jitter.
        on_retry: Callback ``(exception, attempt, delay)`` gọi trước mỗi lần ngủ,
            hữu ích để ghi log/đo lường.

    Returns:
        Giá trị trả về của lần gọi thành công.

    Raises:
        Exception cuối cùng của ``fn`` nếu mọi lần thử đều thất bại, hoặc
        exception không nằm trong ``retry_on``.
    """
    active_policy = policy or RetryPolicy()

    for attempt in range(1, active_policy.attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= active_policy.attempts or not _matches(exc, retry_on):
                raise

            delay = active_policy.delay_for(attempt, rand=rand)
            if on_retry is not None:
                on_retry(exc, attempt, delay)
            sleep(delay)

    # Không thể tới đây: vòng lặp luôn return hoặc raise.
    raise AssertionError("retry loop exited without result")


def retry(
    *,
    policy: RetryPolicy | None = None,
    retry_on: type[BaseException] | tuple[type[BaseException], ...] | Callable[[BaseException], bool] = (
        Exception,
    ),
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator bọc ``retry_call`` cho hàm có tham số."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> T:
            return retry_call(
                lambda: fn(*args, **kwargs),
                policy=policy,
                retry_on=retry_on,
                sleep=sleep,
                rand=rand,
                on_retry=on_retry,
            )

        return wrapper

    return decorator
