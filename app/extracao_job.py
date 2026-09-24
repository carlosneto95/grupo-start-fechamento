"""Executa a sincronização em segundo plano, para a tela não travar durante os
minutos que a API do Tiny leva (limite de 60 chamadas por minuto).

Só uma sincronização roda por vez — o estado fica em memória e a tela consulta o
progresso periodicamente.
"""
from __future__ import annotations

import threading
from datetime import datetime

from app.config.companies import load_companies
from app.sincronizacao import sincronizar
from app.tiny_client.api_client import TinyAPIClient
from app.trava import SincronizacaoEmAndamento

_lock = threading.Lock()
_estado = {
    "rodando": False,
    "etapa": "",
    "feitos": 0,
    "total": 0,
    "erro": None,
    "resumo": None,
    "empresa": None,
    "ano": None,
    "forcado": False,
    "terminado_em": None,
}


def estado_atual() -> dict:
    with _lock:
        return dict(_estado)


def _atualizar(**campos) -> None:
    with _lock:
        _estado.update(campos)


def _executar(empresa, ano: int, forcar: bool) -> None:
    try:
        cliente = TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)

        if not cliente.testar_conexao():
            _atualizar(erro=f"Não consegui conectar na API da empresa {empresa.nome}. Verifique o token no .env.")
            return

        def progresso(feitos, total, etapa):
            _atualizar(feitos=feitos, total=total, etapa=etapa)

        resumo = sincronizar(cliente, empresa.nome, ano, forcar=forcar, progresso=progresso)
        _atualizar(resumo=resumo, etapa="Concluído")
    except SincronizacaoEmAndamento as e:
        _atualizar(erro=str(e))
    except Exception as e:
        _atualizar(erro=f"{type(e).__name__}: {e}")
    finally:
        _atualizar(rodando=False, terminado_em=datetime.now().strftime("%d/%m/%Y %H:%M"))


def iniciar(empresa_key: str, ano: int, forcar: bool = False) -> tuple[bool, str]:
    """Dispara a sincronização numa thread. Retorna (iniciou, mensagem)."""
    empresa = next((e for e in load_companies() if e.key == empresa_key), None)
    if empresa is None:
        return False, "Empresa não encontrada nas configurações (.env)."
    if not empresa.has_api_token:
        return False, f"A empresa {empresa.nome} não tem token de API configurado no .env."

    with _lock:
        if _estado["rodando"]:
            return False, "Já existe uma sincronização em andamento. Aguarde ela terminar."
        _estado.update(
            rodando=True,
            etapa="Iniciando...",
            feitos=0,
            total=0,
            erro=None,
            resumo=None,
            empresa=empresa.nome,
            ano=ano,
            forcado=forcar,
            terminado_em=None,
        )

    threading.Thread(target=_executar, args=(empresa, ano, forcar), daemon=True).start()
    return True, "Sincronização iniciada."
