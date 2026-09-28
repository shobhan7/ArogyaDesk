class AppError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def bad_request(message: str) -> AppError:
    return AppError(400, message)


def unauthorized(message: str = "Invalid email or password") -> AppError:
    return AppError(401, message)


def forbidden(message: str) -> AppError:
    return AppError(403, message)


def not_found(message: str) -> AppError:
    return AppError(404, message)


def conflict(message: str) -> AppError:
    return AppError(409, message)
