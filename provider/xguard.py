from typing import Any

import requests
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin import ToolProvider


class XGuardProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        base_url = credentials.get("xguard_service_url", "").rstrip("/")
        if not base_url:
            raise ToolProviderCredentialValidationError("XGuard Service URL is required.")

        threshold_str = credentials.get("default_threshold", "")
        if threshold_str:
            try:
                threshold = float(threshold_str)
                if not (0.0 <= threshold <= 1.0):
                    raise ValueError
            except (ValueError, TypeError):
                raise ToolProviderCredentialValidationError(
                    "Default threshold must be a number between 0.0 and 1.0."
                )

        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                raise ToolProviderCredentialValidationError(
                    f"Health check returned unexpected status: {data}"
                )
        except requests.RequestException as e:
            raise ToolProviderCredentialValidationError(
                f"Cannot connect to XGuard service at {base_url}/health: {e}"
            )
