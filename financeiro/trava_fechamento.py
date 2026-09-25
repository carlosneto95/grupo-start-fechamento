"""Trava de competência fechada para os AJUSTES MANUAIS (Fase 4.2).

Módulo à parte, sem importar os repositórios, porque são eles que o usam
(repositorio_contas_pagar e receitas) — financeiro/fechamento.py importa os
repositórios, e morar lá criaria import circular.

Decisão do Neto: com o mês fechado, marcar Considerar/Desconsiderar e ajustar
competência ou categoria de nota daquele mês são recusados até um Admin
reabrir. Mudança vinda do Tiny (sincronização) NÃO passa por aqui: o sistema
é espelho do ERP; ela vira diferença pós-fechamento.
"""

from __future__ import annotations

import sqlite3


class CompetenciaFechada(Exception):
    """A linha (ou o destino de um ajuste) está numa competência fechada."""

    def __init__(self, competencia: str):
        super().__init__(
            f"competência {competencia} fechada — um Admin precisa reabrir para alterar"
        )
        self.competencia = competencia


def exigir_aberta(conn: sqlite3.Connection, *competencias: str | None) -> None:
    """Erra se qualquer uma das competências estiver fechada (vazias passam)."""
    for competencia in competencias:
        competencia = (competencia or "").strip()
        if not competencia:
            continue
        fechada = conn.execute(
            "SELECT 1 FROM fechamentos WHERE competencia = ? AND reaberto_em IS NULL",
            (competencia,),
        ).fetchone()
        if fechada:
            raise CompetenciaFechada(competencia)
