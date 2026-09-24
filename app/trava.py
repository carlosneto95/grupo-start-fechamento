"""Trava que garante uma única sincronização por vez.

Sem isso, duas execuções simultâneas (por exemplo, o botão da tela e o script da
linha de comando) disputam a mesma cota de chamadas por minuto da conta no Tiny:
cada uma faz a outra tomar bloqueio de rate limit, e as duas ficam lentas.

A trava fica no banco (e não em memória) justamente para valer entre processos
diferentes. Ela é renovada durante o trabalho; se o processo morrer sem liberar,
a trava expira sozinha depois de alguns minutos.
"""
from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.db import get_conn

# Se a trava não for renovada nesse tempo, considera-se que o dono morreu.
VALIDADE_MINUTOS = 5


class SincronizacaoEmAndamento(Exception):
    pass


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _identificacao() -> str:
    return f"{socket.gethostname()}/pid {os.getpid()}"


def status(empresa: str) -> dict | None:
    """Quem está sincronizando essa empresa agora, ou None se estiver livre."""
    conn = get_conn()
    try:
        linha = conn.execute(
            "SELECT * FROM trava_sincronizacao WHERE empresa = ?", (empresa,)
        ).fetchone()
    finally:
        conn.close()

    if linha is None:
        return None

    visto_em = datetime.fromisoformat(linha["visto_em"])
    if _agora() - visto_em > timedelta(minutes=VALIDADE_MINUTOS):
        return None  # dono sumiu, trava expirada
    return dict(linha)


def renovar(empresa: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE trava_sincronizacao SET visto_em = ? WHERE empresa = ?",
            (_agora().isoformat(), empresa),
        )
        conn.commit()
    finally:
        conn.close()


def liberar(empresa: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM trava_sincronizacao WHERE empresa = ?", (empresa,))
        conn.commit()
    finally:
        conn.close()


@contextmanager
def adquirir(empresa: str):
    """Pega a trava dessa empresa, ou levanta SincronizacaoEmAndamento se já houver
    outra sincronização da MESMA empresa rodando."""
    dono_atual = status(empresa)
    if dono_atual:
        raise SincronizacaoEmAndamento(
            f"Já existe uma sincronização de {empresa} em andamento ({dono_atual['dono']}, "
            f"iniciada em {dono_atual['iniciada_em'][:19].replace('T', ' ')} UTC). "
            "Aguarde ela terminar."
        )

    agora = _agora().isoformat()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO trava_sincronizacao (empresa, dono, iniciada_em, visto_em) "
            "VALUES (?, ?, ?, ?)",
            (empresa, _identificacao(), agora, agora),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        yield
    finally:
        liberar(empresa)
