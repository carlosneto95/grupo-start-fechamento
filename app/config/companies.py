"""Carrega a configuração das 3 empresas (mesmo ERP Tiny, contas separadas) a partir do .env."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent.parent
load_dotenv(RAIZ / ".env")


@dataclass
class CompanyConfig:
    key: str
    nome: str
    tiny_api_token: str | None
    tiny_user: str | None
    tiny_pass: str | None

    @property
    def has_api_token(self) -> bool:
        return bool(self.tiny_api_token)

    @property
    def has_http_credentials(self) -> bool:
        return bool(self.tiny_user and self.tiny_pass)


def _load_company(prefix: str) -> CompanyConfig:
    return CompanyConfig(
        key=prefix,
        nome=os.getenv(f"{prefix}_NOME", prefix),
        tiny_api_token=os.getenv(f"{prefix}_TINY_API_TOKEN") or None,
        tiny_user=os.getenv(f"{prefix}_TINY_USER") or None,
        tiny_pass=os.getenv(f"{prefix}_TINY_PASS") or None,
    )


def load_companies() -> list[CompanyConfig]:
    prefixes = ["EMPRESA1", "EMPRESA2", "EMPRESA3"]
    companies = [_load_company(p) for p in prefixes]
    return [c for c in companies if c.has_api_token or c.has_http_credentials]
