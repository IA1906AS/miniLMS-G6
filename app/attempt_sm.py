from .errors import InvalidAttemptState

IN_PROGRESS = "IN_PROGRESS"
SUBMITTED = "SUBMITTED"
GRADED = "GRADED"

SAVE = "SAVE"
SUBMIT = "SUBMIT"
GRADE = "GRADE"

TRANSITIONS = {
    (IN_PROGRESS, SAVE): IN_PROGRESS,
    (IN_PROGRESS, SUBMIT): SUBMITTED,
    (SUBMITTED, GRADE): GRADED,
}


def transition(current, action):
    try:
        return TRANSITIONS[(current, action)]
    except KeyError:
        raise InvalidAttemptState(
            f"Hành động {action} không được phép ở trạng thái {current}"
        ) from None
