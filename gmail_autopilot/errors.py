"""Domain errors. Every external library exception is normalized into one of these
at the adapter boundary, so higher layers never see a raw httpx/google-api exception."""


class WorkflowError(Exception):
    """Base for all errors raised by this package."""


class TransientError(WorkflowError):
    """Likely temporary. The retry layer will retry these."""


class PermanentError(WorkflowError):
    """Will not succeed on retry. Record on the brief and continue."""


class AuthError(WorkflowError):
    """Credentials are bad. Aborts the entire run."""


class ValidationError(PermanentError):
    """Input or output failed schema validation. Subtype of PermanentError because
    a malformed payload will be malformed on retry too."""
