"""Carrega as 3 contas do Tiny (mesmo ERP, contas separadas) a partir do .env.

Os nomes seguem o prefixo do projeto: GSF_EMPRESA1_NOME, GSF_EMPRESA1_TINY_API_TOKEN...
A leitura passa por `app.configuracao.variaveis()`, que lê o arquivo direto e
NÃO copia os tokens para `os.environ` — no PythonAnywhere o processo é
compartilhado com outros sistemas (ver a explicação em financeiro/configuracao.py).
"""

from dataclasses import dataclass

from financeiro.configuracao import variaveis

EMPRESAS = ("EMPRESA1", "EMPRESA2", "EMPRESA3")


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

    def __repr__(self) -> str:
        # O repr padrão do dataclass imprimiria o token num log ou traceback.
        return f"CompanyConfig(key={self.key!r}, nome={self.nome!r}, token={'***' if self.tiny_api_token else None})"


def _load_company(prefix: str, v: dict) -> CompanyConfig:
    def ler(campo):
        return v.get(f"GSF_{prefix}_{campo}") or None

    return CompanyConfig(
        key=prefix,
        nome=ler("NOME") or prefix,
        tiny_api_token=ler("TINY_API_TOKEN"),
        tiny_user=ler("TINY_USER"),
        tiny_pass=ler("TINY_PASS"),
    )


def load_companies() -> list[CompanyConfig]:
    v = variaveis()
    companies = [_load_company(p, v) for p in EMPRESAS]
    return [c for c in companies if c.has_api_token or c.has_http_credentials]
