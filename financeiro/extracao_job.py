"""Roda o job único de sincronização (financeiro/sincronizar_tudo.py) em segundo
plano, para a tela não travar durante os minutos que a API do Tiny leva
(limite de chamadas por minuto de cada conta).

Só uma execução da TELA por vez neste processo: o estado de progresso fica em
memória e a tela consulta periodicamente. A trava entre processos (tela ×
linha de comando × tarefa agendada) é a do banco, em financeiro/trava.py.
"""

from __future__ import annotations

import threading

from financeiro import sincronizacao, sincronizar_tudo
from financeiro.config.companies import load_companies
from financeiro.db import agora_brasilia

TODAS = "TODAS"

_lock = threading.Lock()
_estado: dict = {
    "rodando": False,
    "empresa": None,
    "tipo": None,
    "etapa": "",
    "feitos": 0,
    "total": 0,
    "resultados": [],
    "erro": None,
    "terminado_em": None,
}


def estado_atual() -> dict:
    with _lock:
        return {**_estado, "resultados": list(_estado["resultados"])}


def _atualizar(**campos) -> None:
    with _lock:
        _estado.update(campos)


def _executar(pedido: sincronizar_tudo.Pedido) -> None:
    def progresso(empresa, tipo, feitos, total, etapa):
        _atualizar(empresa=empresa, tipo=tipo, feitos=feitos, total=total, etapa=etapa)

    try:
        resultados = sincronizar_tudo.executar(pedido, progresso=progresso)
        _atualizar(
            resultados=[
                {
                    "empresa": r.empresa,
                    "tipo": r.tipo,
                    "status": r.status,
                    "erro": r.erro,
                    "encontradas": r.resumo.get("encontradas"),
                    "novas": r.resumo.get("novas"),
                    "atualizadas": r.resumo.get("atualizadas"),
                    # As mudanças detalhadas (fornecedor: de -> para) vêm só das contas.
                    "mudancas": r.resumo.get("mudancas", []),
                    "mudancas_total": r.resumo.get("mudancas_total", 0),
                }
                for r in resultados
            ],
            etapa="Concluído",
        )
    except Exception as e:  # defesa final: nunca deixar a tela "rodando" para sempre
        _atualizar(erro=sincronizar_tudo._texto_erro(e))
    finally:
        _atualizar(rodando=False, terminado_em=agora_brasilia())


def iniciar(empresa_key: str, ano: int, forcar: bool = False) -> tuple[bool, str]:
    """Dispara a sincronização (contas e notas) numa thread. `empresa_key` é
    EMPRESA1/2/3 ou TODAS. Devolve (iniciou, mensagem)."""
    configuradas = load_companies()
    if empresa_key == TODAS:
        empresas = [e for e in configuradas if e.has_api_token]
    else:
        empresas = [e for e in configuradas if e.key == empresa_key and e.has_api_token]
    if not empresas:
        return False, "Empresa não encontrada ou sem token de API no .env."

    pedido = sincronizar_tudo.Pedido(
        empresas=empresas,
        periodo=sincronizacao.periodo_do_ano(ano),
        origem="tela",
        forcar=forcar,
    )

    with _lock:
        if _estado["rodando"]:
            return False, "Já existe uma sincronização em andamento. Aguarde ela terminar."
        _estado.update(
            rodando=True,
            empresa=None,
            tipo=None,
            etapa="Iniciando...",
            feitos=0,
            total=0,
            resultados=[],
            erro=None,
            terminado_em=None,
        )

    threading.Thread(target=_executar, args=(pedido,), daemon=True).start()
    return True, "Sincronização iniciada."
