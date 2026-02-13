"""Core typed models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class SectionType(StrEnum):
    """Template section classifications."""

    FILL = "fill"
    SKIP = "skip"
    VALIDATOR = "validator"


class TemplateFormat(StrEnum):
    """Supported template formats."""

    DOCX = "docx"
    MARKDOWN = "markdown"


class DraftStatus(StrEnum):
    """Status for generated section content."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class AuthMode(StrEnum):
    """Authentication mode for Gemini access."""

    API = "api"
    M2M = "m2m"
    H2M = "h2m"


class CheckboxToken(BaseModel):
    """Checkbox declaration in template/draft."""

    name: str
    checked: bool = False


class TemplateSection(BaseModel):
    """Parsed section from template."""

    id: str
    title: str
    section_type: SectionType
    marker_text: str
    heading_index: int
    body_text: str = ""
    checkbox_tokens: list[str] = Field(default_factory=list)


class ParsedTemplate(BaseModel):
    """Entire parsed template payload."""

    source_path: str
    template_format: TemplateFormat = TemplateFormat.DOCX
    template_stem: str | None = None
    sections: list[TemplateSection] = Field(default_factory=list)
    parser_errors: list[str] = Field(default_factory=list)


class MissingItem(BaseModel):
    """Missing item that user can fill in context file."""

    id: str
    section_id: str
    question: str
    user_response: str = ""


class DraftSection(BaseModel):
    """Generated section content."""

    id: str
    title: str
    status: DraftStatus
    checkboxes: list[CheckboxToken] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_items: list[MissingItem] = Field(default_factory=list)
    body: str = ""

    @model_validator(mode="after")
    def ensure_evidence_or_missing(self) -> DraftSection:
        """Enforce minimum evidence quality."""
        if not self.evidence and not self.missing_items:
            raise ValueError(
                f"Section '{self.id}' must include at least one evidence entry or missing item."
            )
        return self


class DraftDocument(BaseModel):
    """Draft markdown object model."""

    sections: list[DraftSection] = Field(default_factory=list)


class ApplyReport(BaseModel):
    """Result of apply operation."""

    output_path: str
    unresolved_section_ids: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Runtime configuration."""

    model: str = "gemini-3-flash-preview"
    provider: str = "google_ai_studio"
    auth_mode: AuthMode = AuthMode.API
    vertexai: bool = False
    google_project: str | None = None
    google_location: str = "us-central1"
    https_proxy: str | None = None
    ssl_cert_file: str | None = None
    temperature: float = 0.1
    max_section_tokens: int = 4000
    context_file: str = "additional-context.md"
    output_root: str = "outputs"
    fallback_model: str = "gemini-2.5-flash"
    repo_allowlist: list[str] = Field(
        default_factory=lambda: [
            "*.py",
            "*.md",
            "*.yaml",
            "*.yml",
            "*.json",
            "*.toml",
            "*.txt",
            "*.ipynb",
        ]
    )
    repo_denylist: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            "venv/**",
            ".venv/**",
            "node_modules/**",
            "*.parquet",
            "*.bin",
            "*.pt",
            "*.pkl",
        ]
    )
    google_api_key: str | None = None
    m2m_token_url: str | None = None
    m2m_client_id: str | None = None
    m2m_client_secret: str | None = None
    m2m_scope: str | None = None
    m2m_audience: str | None = None
    m2m_grant_type: str = "client_credentials"
    m2m_token_field: str = "access_token"
    m2m_expires_in_field: str = "expires_in"
    m2m_auth_style: str = "body"
    m2m_token_timeout: int = 30
    h2m_token_ttl: int = 3600
