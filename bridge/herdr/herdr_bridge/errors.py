"""The closed set of error codes the bridge answers with, each with its HTTP status."""

STATUS: dict[str, int] = {
    "bad_request": 400,
    "bad_path": 400,
    "bad_token": 401,
    "wrong_person": 403,
    "dir_not_allowed": 403,
    "not_found": 404,
    "busy": 409,
    "blocked": 409,
    "unknown_state": 409,
    "label_taken": 409,
    "too_many": 409,
    "too_large": 413,
    "herdr_unavailable": 503,
    "unconfirmed": 504,
}


class BridgeError(Exception):
    """A refusal or failure that reaches the caller as `{"error": code}` with the code's status."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.status = STATUS[code]
