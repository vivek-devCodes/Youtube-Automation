class StudioError(Exception):
    """Base error. `retryable` tells the workflow engine whether to back off and retry."""

    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None):
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class ProviderError(StudioError):
    retryable = True


class ProviderNotConfigured(StudioError):
    retryable = False


class BudgetExceeded(StudioError):
    retryable = False


class ComplianceFailure(StudioError):
    retryable = False


class QualityFailure(StudioError):
    retryable = False


class YouTubeError(StudioError):
    retryable = True


class QuotaExceeded(YouTubeError):
    retryable = False
