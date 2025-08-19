class LBankError(Exception):
    def __init__(self, code: int | None = None, message: str | None = None):
        self.code = code
        self.message = message or "LBank API error"
        super().__init__(f"[{self.code}] {self.message}")


class RateLimitError(LBankError):
    pass


class TimeDriftError(LBankError):
    pass
