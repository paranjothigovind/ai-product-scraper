from scraper.schemas.error_code import ErrorCode


class ScrapeError(Exception):
    """A failure that maps onto a stable, client-facing error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after
