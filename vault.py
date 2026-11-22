"""Read secrets from Azure Key Vault, with environment variables as the fallback.

The app's service principal (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET) must have get and list on the
vault (AZURE_KEYVAULT_URL). Values are cached in memory for the life of the process. They are never logged.
"""
from __future__ import annotations

import os
import threading

_cache: dict[str, str | None] = {}
_lock = threading.Lock()


def _vault_client():
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    url = os.environ["AZURE_KEYVAULT_URL"]
    tenant, client, secret = (os.environ.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
    cred = ClientSecretCredential(tenant, client, secret) if (tenant and client and secret) else DefaultAzureCredential()
    return SecretClient(vault_url=url, credential=cred)


def get(name: str, env_name: str | None = None) -> str | None:
    """The secret's value, or None. Env var `env_name` (default: the name upper-cased with _) wins when set."""
    env_name = env_name or name.upper().replace("-", "_")
    if os.environ.get(env_name):
        return os.environ[env_name]
    if not os.environ.get("AZURE_KEYVAULT_URL"):
        return None
    with _lock:
        if name not in _cache:
            try:
                _cache[name] = _vault_client().get_secret(name).value
            except Exception:  # noqa: BLE001 - a missing secret is a configuration state, not a crash
                _cache[name] = None
        return _cache[name]
