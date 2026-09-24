"""Trilha de auditoria: quem mudou o quê, quando, e o valor antes e depois.

Toda escrita MANUAL passa por aqui — marcar Considerar, ajustar competência
ou categoria de nota, mudar regra de exclusão. Dado que chega do Tiny pela
sincronização não é auditado aqui: ele tem o próprio histórico em
`sincronizacoes`, e o Tiny é a origem.

A gravação usa a MESMA conexão (e transação) da escrita auditada: se a
escrita for desfeita, a auditoria some junto; se a auditoria falhar, a
escrita não acontece. Não existe mudança sem registro.

A tabela é append-only: triggers no banco recusam UPDATE e DELETE
(migração 2).
"""

from __future__ import annotations

import json
import sqlite3

from app.db import agora_brasilia


def _autor() -> tuple[str, str | None]:
    """(usuário, ip). Até a Fase 2 não há login: o usuário é o configurado em
    GSF_USUARIO_PADRAO. Fora de requisição (script, sincronização), "cli"."""
    try:
        from flask import current_app, has_request_context, request

        if has_request_context():
            return current_app.config.get("USUARIO_PADRAO", "local"), request.remote_addr
    except RuntimeError:
        pass
    return "cli", None


def _json(valor) -> str | None:
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def registrar(
    conn: sqlite3.Connection,
    acao: str,
    entidade: str,
    entidade_id: str | None,
    empresa: str | None,
    antes,
    depois,
) -> None:
    """Grava uma linha. NÃO dá commit: quem chama confirma junto com a escrita."""
    usuario, ip = _autor()
    conn.execute(
        "INSERT INTO auditoria (data_hora, usuario, acao, entidade, entidade_id, empresa,"
        " valor_anterior, valor_novo, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            agora_brasilia(),
            usuario,
            acao,
            entidade,
            entidade_id,
            empresa,
            _json(antes),
            _json(depois),
            ip,
        ),
    )
