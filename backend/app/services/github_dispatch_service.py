"""Server-only GitHub Actions ``workflow_dispatch`` abstraction.

The dispatch token is read from server configuration, sent only in the
Authorization header, and never returned, logged, or echoed. When the token or
repository is unset the service reports itself disabled and the arm request
fails closed rather than silently doing nothing.
"""

import requests

from backend.app.core.config import Settings, settings


class GitHubDispatchError(RuntimeError):
    """Raised when a workflow dispatch could not be accepted by GitHub."""

    def __init__(self, message: str, *, code: str = "DISPATCH_FAILED") -> None:
        super().__init__(message)
        self.code = code


class GitHubDispatchService:
    def __init__(self, *, config: Settings = settings) -> None:
        self.config = config

    def is_enabled(self) -> bool:
        return bool(
            (self.config.regret_github_dispatch_token or "").strip()
            and (self.config.regret_github_repository or "").strip()
            and (self.config.regret_github_workflow or "").strip()
        )

    def target(self) -> dict:
        """Non-secret description of the dispatch target, safe to expose."""
        return {
            "repository": self.config.regret_github_repository,
            "workflow": self.config.regret_github_workflow,
            "ref": self.config.regret_github_ref,
            "enabled": self.is_enabled(),
        }

    def dispatch_cycle(self, *, arm_session_id: str) -> dict:
        """Trigger exactly one one-shot workflow run for this arm session."""
        if not self.is_enabled():
            raise GitHubDispatchError(
                "GitHub dispatch is not configured.",
                code="DISPATCH_DISABLED",
            )

        repository = str(self.config.regret_github_repository).strip()
        workflow = str(self.config.regret_github_workflow).strip()
        url = (
            f"{str(self.config.regret_github_api_base_url).rstrip('/')}"
            f"/repos/{repository}/actions/workflows/{workflow}/dispatches"
        )

        try:
            response = requests.post(
                url,
                json={
                    "ref": self.config.regret_github_ref,
                    # Only the non-secret correlation id is ever sent.
                    "inputs": {"arm_session_id": arm_session_id},
                },
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Authorization": (
                        f"Bearer {self.config.regret_github_dispatch_token}"
                    ),
                },
                timeout=self.config.regret_github_dispatch_timeout_seconds,
            )
        except requests.RequestException as exc:
            # Never include the exception's request context: it can carry
            # the Authorization header.
            raise GitHubDispatchError(
                f"GitHub dispatch request failed: {type(exc).__name__}",
            ) from None

        if response.status_code not in (201, 204):
            raise GitHubDispatchError(
                "GitHub rejected the workflow dispatch "
                f"(HTTP {response.status_code}).",
            )

        return {
            "dispatched": True,
            "repository": repository,
            "workflow": workflow,
            "ref": self.config.regret_github_ref,
            "status_code": response.status_code,
        }


github_dispatch_service = GitHubDispatchService()
