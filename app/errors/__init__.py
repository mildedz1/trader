class ExchangeError(Exception):
    def __init__(self, code: int | None = None, message: str | None = None):
        self.code = code
        self.message = message or "Exchange API error"
        super().__init__(f"[{self.code}] {self.message}")


class RateLimitError(ExchangeError):
    pass


class TimeDriftError(ExchangeError):
    pass
