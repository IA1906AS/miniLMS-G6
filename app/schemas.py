from .errors import ValidationError


def validate_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError()
    if not 0 <= value <= 10:
        raise ValidationError()
    return value


def validate_grade_body(payload):
    if not isinstance(payload, dict):
        raise ValidationError()
    keys = set(payload.keys())
    if keys not in [{"score"}, {"score", "version"}]:
        raise ValidationError()
    score = validate_score(payload["score"])
    version = payload.get("version")
    if version is not None:
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError()
    return score, version
