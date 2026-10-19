from .errors import ValidationError


def validate_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError()
    if not 0 <= value <= 10:
        raise ValidationError()
    return value


def validate_grade_body(payload):
    if not isinstance(payload, dict) or set(payload) != {"score"}:
        raise ValidationError()
    return validate_score(payload["score"])
