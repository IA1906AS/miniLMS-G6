class ApiError(Exception):
    status = 500
    code = "INTERNAL_ERROR"


class ValidationError(ApiError):
    status = 400
    code = "VALIDATION_ERROR"


class InvalidCredentials(ApiError):
    status = 401
    code = "INVALID_CREDENTIALS"


class Unauthenticated(ApiError):
    status = 401
    code = "UNAUTHENTICATED"


class Forbidden(ApiError):
    status = 403
    code = "FORBIDDEN"


class NotFound(ApiError):
    status = 404
    code = "NOT_FOUND"


class AccountLocked(ApiError):
    status = 429
    code = "ACCOUNT_LOCKED"


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return {"error": e.code}, e.status

    @app.errorhandler(Forbidden)
    def _handle_forbidden(e):
        from flask import g, has_request_context, request

        if has_request_context():
            from audit import log_event

            actor = getattr(g, "actor", None)
            log_event(
                actor.get("id") if isinstance(actor, dict) else None,
                request.method,
                request.path,
                "FORBIDDEN",
            )
        return {"error": "FORBIDDEN"}, 403

    @app.errorhandler(400)
    def _handle_bad_request(e):
        return {"error": "VALIDATION_ERROR"}, 400

    @app.errorhandler(404)
    def _handle_not_found(e):
        return {"error": "NOT_FOUND"}, 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(e):
        return {"error": "METHOD_NOT_ALLOWED"}, 405

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return {"error": "INTERNAL_ERROR"}, 500
