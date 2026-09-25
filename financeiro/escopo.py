"""O "RLS" do sistema: quem está pedindo e quais empresas pode ver.

O SQLite não tem Row Level Security. A trava mora aqui, numa função única:
todo SQL sobre dado de empresa (contas_pagar, notas) monta o filtro com
`clausula(escopo)`, e ela ERRA se o escopo faltar — não existe como esquecer
o filtro em silêncio. Padrão do Controle de Impostos (sistema/dados.py).

Quem monta o escopo:
  - na web, financeiro/seguranca.carregar_escopo, a cada requisição, LENDO O BANCO
    (perfil e empresas nunca vêm do cookie, de campo oculto ou da URL);
  - nos scripts e no job de sincronização, `SISTEMA`, que tem poder de Admin
    e aparece como "sistema" na auditoria.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PERFIS = ("admin", "financeiro", "leitura")


class ErroEscopo(Exception):
    """Erro de PROGRAMAÇÃO: consulta sem escopo, ou operação que o perfil não
    permite chegando ao repositório. Nunca deve chegar ao usuário como texto."""


@dataclass(frozen=True)
class Escopo:
    usuario_id: int | None
    login: str
    perfil: str
    # Empresas permitidas. Ignorado para Admin, que vê todas — inclusive uma
    # empresa nova que a sincronização trouxer, sem precisar reatribuir.
    empresas: frozenset[str] = frozenset()

    def __post_init__(self):
        if self.perfil not in PERFIS:
            raise ErroEscopo(f"perfil inválido: {self.perfil}")

    @property
    def eh_admin(self) -> bool:
        return self.perfil == "admin"

    @property
    def pode_escrever(self) -> bool:
        """Marcar Considerar e ajustar nota: Admin e Financeiro."""
        return self.perfil in ("admin", "financeiro")

    def pode(self, empresa: str | None) -> bool:
        return self.eh_admin or (empresa in self.empresas)


# Escopo dos scripts, da sincronização e da tarefa agendada: roda sem usuário
# logado, com poder de Admin, e assina "sistema" na auditoria.
SISTEMA = Escopo(usuario_id=None, login="sistema", perfil="admin")

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?")


def exigir(escopo) -> Escopo:
    if not isinstance(escopo, Escopo):
        raise ErroEscopo("consulta a dado de empresa sem escopo")
    return escopo


def clausula(escopo, coluna: str = "empresa") -> tuple[str, list]:
    """Filtro de empresa para o WHERE, com os valores como PARÂMETROS (?).

      Admin              -> "1 = 1"
      sem empresa        -> "0 = 1"   (não vê nada, em vez de ver tudo)
      demais             -> "empresa IN (?, ?)"

    `coluna` é escrita no código, nunca vem do usuário; mesmo assim é
    conferida contra o formato de identificador SQL."""
    exigir(escopo)
    if not _IDENTIFICADOR.fullmatch(coluna):
        raise ErroEscopo(f"nome de coluna inválido: {coluna!r}")
    if escopo.eh_admin:
        return "1 = 1", []
    if not escopo.empresas:
        return "0 = 1", []
    empresas = sorted(escopo.empresas)
    return f"{coluna} IN ({', '.join('?' * len(empresas))})", empresas


def exigir_escrita(escopo, empresa: str | None) -> bool:
    """Pode gravar nesta empresa? False = trate como "não existe" (404): quem
    não enxerga a empresa não pode nem confirmar que o registro existe."""
    exigir(escopo)
    return escopo.pode_escrever and escopo.pode(empresa)


def exigir_admin(escopo) -> None:
    if not exigir(escopo).eh_admin:
        raise ErroEscopo("operação administrativa sem perfil Admin")
