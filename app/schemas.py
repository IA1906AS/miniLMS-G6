from .errors import ValidationError


def validate_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError()
    if not 0 <= value <= 10:
        raise ValidationError()
    return value


def validate_grade_body(payload):
    if not isinstance(payload, dict) or set(payload.keys()) != {"score", "version"}:
        raise ValidationError()
    score = validate_score(payload["score"])
    version = payload["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError()
    return score, version


def validate_answers(value):
    """Câu trả lời là chuỗi 1..4000 ký tự sau khi strip."""
    if not isinstance(value, str):
        raise ValidationError()
    stripped = value.strip()
    if not 1 <= len(stripped) <= 4000:
        raise ValidationError()
    return stripped
