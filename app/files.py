"""Upload helpers: validate and persist files on local disk."""

import logging
from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename

from .errors import ValidationError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "zip", "txt"}
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def save_upload(
    upload_dir,
    storage,
    subdir,
    *,
    allowed_extensions=None,
    max_bytes=MAX_UPLOAD_BYTES,
):
    """Validate a FileStorage and persist it; returns (stored_name, original_name, size)."""
    original = secure_filename(storage.filename or "")
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    allowed = allowed_extensions if allowed_extensions is not None else ALLOWED_EXTENSIONS
    if not original or ext not in allowed:
        raise ValidationError()
    data = storage.read()
    if not data or len(data) > max_bytes:
        raise ValidationError()
    stored = f"{uuid4().hex}_{original}"
    target = Path(upload_dir) / subdir
    target.mkdir(parents=True, exist_ok=True)
    (target / stored).write_bytes(data)
    return stored, original, len(data)


def upload_path(upload_dir, subdir, stored_name):
    return Path(upload_dir) / subdir / stored_name


def delete_upload(upload_dir, subdir, stored_name):
    """Xoá tệp đã lưu; không để lỗi hệ tệp biến request xoá thành 500.

    Trên Windows, tệp đang được một lượt tải khác mở sẽ không xoá được
    (PermissionError / WinError 32). Bản ghi đã bị xoá khỏi DB trước đó nên
    trả 500 chỉ gây hiểu nhầm; ghi cảnh báo để dọn tệp mồ côi sau.
    """
    if not stored_name:
        return
    try:
        upload_path(upload_dir, subdir, stored_name).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "Không xoá được tệp tải lên %s/%s: %s", subdir, stored_name, exc
        )

