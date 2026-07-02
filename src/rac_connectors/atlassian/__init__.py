"""Atlassian connector: Jira reference verification and Confluence publish.

The suite lives here per rac-core ADR-090; the seams and client decisions are
ADR-010, the publish identity model is ADR-011, and the module shape is the
``atlassian-connector-shape`` design.
"""

from .client import (
    BASE_URL_ENV,
    EMAIL_ENV,
    SPACE_ENV,
    TOKEN_ENV,
    AtlassianAuthError,
    BulkFetchResult,
    ConfluenceClient,
    HttpAtlassianClient,
    IssueState,
    JiraClient,
    ManagedPage,
    MissingCredentialsError,
    VersionConflictError,
    client_from_env,
)
from .connector import BACKEND, AtlassianPublisher, AtlassianVerifier

__all__ = [
    "BACKEND",
    "AtlassianPublisher",
    "AtlassianVerifier",
    "BASE_URL_ENV",
    "EMAIL_ENV",
    "SPACE_ENV",
    "TOKEN_ENV",
    "AtlassianAuthError",
    "BulkFetchResult",
    "ConfluenceClient",
    "HttpAtlassianClient",
    "IssueState",
    "JiraClient",
    "ManagedPage",
    "MissingCredentialsError",
    "VersionConflictError",
    "client_from_env",
]
