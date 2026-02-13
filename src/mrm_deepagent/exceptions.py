"""Project-specific exceptions."""


class MRMDeepAgentError(Exception):
    """Base exception for the project."""


class MissingRuntimeConfigError(MRMDeepAgentError):
    """Raised when required runtime configuration is missing."""


class TemplateValidationError(MRMDeepAgentError):
    """Raised when template markers are invalid."""


class DraftParseError(MRMDeepAgentError):
    """Raised when draft markdown cannot be parsed or validated."""


class UnsupportedTemplateError(MRMDeepAgentError):
    """Raised when a DOCX feature is unsupported by applier."""


class AlreadyAppliedError(MRMDeepAgentError):
    """Raised when apply is attempted on an already-applied file."""
