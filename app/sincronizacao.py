"""Sincroniza o banco local com o Tiny, guardando TODAS as contas do período
(não só as de uma competência) e classificando a competência de cada uma.

Ideia central: a listagem da API é barata (até 100 contas por chamada) e já traz
valor, saldo, situação e datas. O detalhe — único lugar onde a competência
aparece — é caro (1 conta por chamada, ~1/segundo). Então listamos tudo, comparamos
com o banco, e só pagamos o detalhe de quem é novo ou mudou.

Dois modos:
  - normal:  detalha só o que é novo ou teve mudança visível na listagem.
  - forçado: redetalha tudo, para pegar edição "silenciosa" (ex: mudaram só a
             competência ou a categoria, que não aparecem na listagem).
"""
from __future__ import annotations

from datetime import date

from app.reports.contas_pagar import _registro_para_linha
from app.repositorio_contas_pagar import mapa_por_id, upsert_contas
from app.escopo import SISTEMA
from app.trava import renovar

# Campos que a listagem devolve e dá para comparar com o banco para achar mudanças.
CAMPOS_COMPARAVEIS = [
    ("valor", "valor", "numero"),
    ("saldo", "saldo", "numero"),
    ("situacao", "situacao", "texto"),
    ("data_emissao", "data_emissao", "texto"),
    ("data_vencimento", "data_vencimento", "texto"),
]

# Grava a cada N detalhes para que uma queda no meio não perca o já feito.
TAMANHO_LOTE = 25


def _normalizar(valor, tipo: str):
    if valor is None or valor == "":
        return None
    if tipo == "numero":
        try:
            return round(float(valor), 2)
        except (TypeError, ValueError):
            return None
    return str(valor).strip()


def _mudancas_na_listagem(resumo: dict, gravado: dict) -> list[str]:
    """Campos da listagem que estão diferentes do que temos no banco."""
    diferentes = []
    for campo_api, campo_banco, tipo in CAMPOS_COMPARAVEIS:
        if _normalizar(resumo.get(campo_api), tipo) != _normalizar(gravado.get(campo_banco), tipo):
            diferentes.append(campo_banco)
    return diferentes


def _diferencas_no_detalhe(nova: dict, antiga: dict) -> list[dict]:
    """Compara a linha pronta (pós-detalhe) com a que estava no banco."""
    interessantes = ["competencia", "valor", "saldo", "situacao", "categoria",
                     "data_vencimento", "data_liquidacao", "forma_pagamento"]
    mudancas = []
    for campo in interessantes:
        antes = antiga.get(campo)
        depois = nova.get(campo)
        tipo = "numero" if campo in ("valor", "saldo") else "texto"
        if _normalizar(antes, tipo) != _normalizar(depois, tipo):
            mudancas.append({"campo": campo, "de": antes, "para": depois})
    return mudancas


def periodo_do_ano(ano: int) -> tuple[date, date]:
    """O ano inteiro com 2 meses de folga nas pontas.

    A folga é necessária porque competência diverge de emissão/vencimento: uma
    conta emitida em nov/2025 pode ter competência 01/2026, e uma de dez/2026
    pode vencer em 2027. Sem a folga, essas ficariam de fora."""
    return date(ano - 1, 11, 1), date(ano + 1, 2, 28)




def _sincronizar(cliente, empresa_nome: str, periodo: tuple[date, date], forcar: bool,
                 progresso, por: tuple[str, ...]) -> dict:
    def avisar(feitos, total, etapa):
        if progresso:
            progresso(feitos, total, etapa)

    data_ini, data_fim = periodo
    rotulo = f"{data_ini.strftime('%m/%Y')} a {data_fim.strftime('%m/%Y')}"
    avisar(0, 0, f"Listando contas de {rotulo} no Tiny...")

    def ao_listar(qtd):
        renovar(empresa_nome)
        avisar(0, qtd, f"Listando contas de {rotulo} no Tiny...")

    resumos = cliente.listar_resumo(data_ini, data_fim, progresso=ao_listar, por=por)

    gravadas = mapa_por_id(SISTEMA, empresa_nome)

    a_detalhar: list[str] = []
    novos = set()
    for id_conta, resumo in resumos.items():
        gravado = gravadas.get(id_conta)
        if gravado is None:
            novos.add(id_conta)
            a_detalhar.append(id_conta)
        elif forcar or _mudancas_na_listagem(resumo, gravado):
            a_detalhar.append(id_conta)

    total = len(a_detalhar)
    etapa = "Rebuscando todas as contas..." if forcar else "Buscando contas novas e alteradas..."
    avisar(0, total, etapa)

    if total == 0:
        return {
            "encontradas": len(resumos), "novas": 0, "atualizadas": 0,
            "sem_mudanca": len(resumos), "mudancas": [],
        }

    lote: list[dict] = []
    mudancas: list[dict] = []
    atualizadas = 0
    gravadas_novas = 0

    def descarregar():
        if lote:
            upsert_contas(SISTEMA, lote)
            lote.clear()

    for i, id_conta in enumerate(a_detalhar, start=1):
        detalhe = cliente.obter_conta_pagar(id_conta)
        if not detalhe:
            avisar(i, total, etapa)
            continue

        linha = _registro_para_linha(detalhe, empresa_nome)
        linha["id"] = str(linha.get("id") or id_conta)

        if id_conta in novos:
            gravadas_novas += 1
        else:
            diferencas = _diferencas_no_detalhe(linha, gravadas[id_conta])
            if diferencas:
                atualizadas += 1
                mudancas.append({
                    "id": id_conta,
                    "fornecedor": linha.get("fornecedor"),
                    "diferencas": diferencas,
                })

        lote.append(linha)
        if len(lote) >= TAMANHO_LOTE:
            descarregar()
            renovar(empresa_nome)  # avisa que continuamos vivos, para a trava não expirar
        avisar(i, total, etapa)

    descarregar()

    return {
        "encontradas": len(resumos),
        "novas": gravadas_novas,
        "atualizadas": atualizadas,
        "sem_mudanca": len(resumos) - gravadas_novas - atualizadas,
        "mudancas": mudancas[:50],
        "mudancas_total": len(mudancas),
    }
