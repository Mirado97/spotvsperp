from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str
    testnet: bool = False


class SecretsVault:
    """
    Reads secrets from .env and environment variables.
    Interface mirrors AWS SSM / HashiCorp Vault for easy future migration.
    Priority: environment variables > .env file.
    """

    def __init__(self, env_file: Path | None = None) -> None:
        path = env_file or _PROJECT_ROOT / ".env"
        load_dotenv(path, override=False)

    def get_exchange_credentials(self, exchange: str) -> ExchangeCredentials:
        prefix = exchange.upper()
        return ExchangeCredentials(
            api_key=self._require(f"{prefix}_API_KEY"),
            api_secret=self._require(f"{prefix}_API_SECRET"),
            testnet=os.getenv(f"{prefix}_TESTNET", "false").lower() == "true",
        )

    def get(self, key: str, default: str | None = None) -> str | None:
        return os.getenv(key, default)

    def _require(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Required secret not found: {key}")
        return value


_vault: SecretsVault | None = None


def get_vault() -> SecretsVault:
    global _vault
    if _vault is None:
        _vault = SecretsVault()
    return _vault
