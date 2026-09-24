"""Traduz os filtros de coluna da URL numa chamada às listagens.

Vive num módulo próprio porque a mesma tradução é usada duas vezes: pela tela,
que lista as linhas, e pelo filtro em cascata, que precisa saber quais linhas
sobrevivem aos *outros* filtros para montar a lista de um funil.

Cada coluna filtrável cai num de três caminhos, e é por isso que não dá para
mandar o dicionário inteiro para o SQL:

  - coluna crua do banco  -> vira WHERE ... IN (...)
  - data e competência    -> casam por prefixo (ano/mês/dia), em Python
  - derivada              -> só existe depois de calcular a linha
                             (valor formatado, considerar/desconsiderar,
                              competência e categoria efetivas das notas)
"""
from __future__ import annotations

from app.receitas import listar_notas
from app.repositorio_contas_pagar import listar_contas

# Colunas que viram WHERE direto na tabela.
SQL_DESPESAS = ("empresa", "fornecedor", "categoria_primaria", "subcategoria", "situacao")
SQL_RECEITAS = ("empresa", "tipo_nota", "numero", "cliente_nome", "descricao_situacao")

# Colunas de data com árvore Ano > Mês > Dia.
DATAS_DESPESAS = ("data_emissao", "data_vencimento", "data_liquidacao")


def _marcados(filtros_coluna: dict, coluna: str) -> set | None:
    """Seleção de uma coluna como conjunto; None quando não há filtro."""
    return set(filtros_coluna.get(coluna) or []) or None


def despesas(filtros_coluna: dict, ordenar=None, direcao="asc") -> list[dict]:
    filtros = {c: filtros_coluna[c] for c in SQL_DESPESAS if filtros_coluna.get(c)}
    return listar_contas(
        filtros,
        {campo: _marcados(filtros_coluna, campo) for campo in DATAS_DESPESAS},
        ordenar=ordenar,
        direcao=direcao,
        competencias=_marcados(filtros_coluna, "competencia"),
        consideracao=_marcados(filtros_coluna, "considerar_efetivo"),
        valores_sel=_marcados(filtros_coluna, "valor"),
    )


def receitas(filtros_coluna: dict, ordenar=None, direcao="desc") -> list[dict]:
    filtros = {c: filtros_coluna[c] for c in SQL_RECEITAS if filtros_coluna.get(c)}
    # A emissão das notas também é árvore de datas, e listar_notas a espera
    # dentro do mesmo dicionário de filtros.
    if filtros_coluna.get("data_emissao"):
        filtros["data_emissao"] = filtros_coluna["data_emissao"]
    return listar_notas(
        filtros,
        competencias=_marcados(filtros_coluna, "competencia_efetiva"),
        ordenar=ordenar,
        direcao=direcao,
        categorias=_marcados(filtros_coluna, "categoria_primaria_efetiva"),
        consideracao=_marcados(filtros_coluna, "considerar_efetivo"),
        valores_sel=_marcados(filtros_coluna, "valor"),
    )


def _receitas_do_tipo(tipo: str):
    """Fecha `receitas` num tipo de nota, para as telas de Vendas e Serviços.

    O tipo é fixado AQUI e não vem da URL de propósito: é a identidade da tela,
    não um filtro que o usuário possa desmarcar. Assim a cascata dos funis, que
    passa por esta mesma função, enxerga só o universo daquela tela."""
    def listar(filtros_coluna: dict, ordenar=None, direcao="desc") -> list[dict]:
        filtros = dict(filtros_coluna)
        filtros["tipo_nota"] = [tipo]
        return receitas(filtros, ordenar=ordenar, direcao=direcao)
    return listar


receitas_vendas = _receitas_do_tipo("venda")
receitas_servicos = _receitas_do_tipo("servico")

LISTAGEM = {
    "despesas": despesas,
    "receitas": receitas,
    "receitas_vendas": receitas_vendas,
    "receitas_servicos": receitas_servicos,
}


def linhas(tabela: str, filtros_coluna: dict) -> list[dict]:
    if tabela not in LISTAGEM:
        raise ValueError(f"tabela desconhecida: {tabela}")
    return LISTAGEM[tabela](filtros_coluna)
