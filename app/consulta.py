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


def despesas(
    escopo, filtros_coluna: dict, ordenar=None, direcao="asc", ordenado=True
) -> list[dict]:
    filtros = {c: filtros_coluna[c] for c in SQL_DESPESAS if filtros_coluna.get(c)}
    return listar_contas(
        escopo,
        filtros,
        {campo: _marcados(filtros_coluna, campo) for campo in DATAS_DESPESAS},
        ordenar=ordenar,
        direcao=direcao,
        competencias=_marcados(filtros_coluna, "competencia"),
        consideracao=_marcados(filtros_coluna, "considerar_efetivo"),
        valores_sel=_marcados(filtros_coluna, "valor"),
        ordenado=ordenado,
    )


def receitas(
    escopo, filtros_coluna: dict, ordenar=None, direcao="desc", ordenado=True
) -> list[dict]:
    filtros = {c: filtros_coluna[c] for c in SQL_RECEITAS if filtros_coluna.get(c)}
    # A emissão das notas também é árvore de datas, e listar_notas a espera
    # dentro do mesmo dicionário de filtros.
    if filtros_coluna.get("data_emissao"):
        filtros["data_emissao"] = filtros_coluna["data_emissao"]
    return listar_notas(
        escopo,
        filtros,
        competencias=_marcados(filtros_coluna, "competencia_efetiva"),
        ordenar=ordenar,
        direcao=direcao,
        categorias=_marcados(filtros_coluna, "categoria_primaria_efetiva"),
        consideracao=_marcados(filtros_coluna, "considerar_efetivo"),
        valores_sel=_marcados(filtros_coluna, "valor"),
        ordenado=ordenado,
    )


def _receitas_do_tipo(tipo: str):
    """Fecha `receitas` num tipo de nota, para as telas de Vendas e Serviços.

    O tipo é fixado AQUI e não vem da URL de propósito: é a identidade da tela,
    não um filtro que o usuário possa desmarcar. Assim a cascata dos funis, que
    passa por esta mesma função, enxerga só o universo daquela tela."""

    def listar(
        escopo, filtros_coluna: dict, ordenar=None, direcao="desc", ordenado=True
    ) -> list[dict]:
        filtros = dict(filtros_coluna)
        filtros["tipo_nota"] = [tipo]
        return receitas(escopo, filtros, ordenar=ordenar, direcao=direcao, ordenado=ordenado)

    return listar


receitas_vendas = _receitas_do_tipo("venda")
receitas_servicos = _receitas_do_tipo("servico")

TIPOS_ORDENACAO_USUARIOS = {
    "login": "texto",
    "nome": "texto",
    "perfil": "texto",
    "empresas_texto": "texto",
    "situacao": "texto",
    "ultimo_login": "texto",
}


def _situacao(u: dict, agora: str) -> str:
    if not u["ativo"]:
        return "inativo"
    if u["bloqueado_ate"] and u["bloqueado_ate"] > agora:
        return "bloqueado"
    if u["deve_trocar_senha"]:
        return "trocar senha"
    return "ativo"


def usuarios_listagem(escopo, filtros_coluna: dict, ordenar=None, direcao="asc", ordenado=True):
    """Usuários para a tela de Admin. usuarios.listar() exige Admin — outro
    perfil nem chega a montar a lista. Filtro em Python: são poucas linhas."""
    from app import usuarios
    from app.db import agora_brasilia
    from app.ordenacao import ordenar_linhas
    from app.visao import SEM_VALOR

    agora = agora_brasilia()
    linhas = usuarios.listar(escopo)
    for u in linhas:
        u["empresas_texto"] = "todas" if u["perfil"] == "admin" else ", ".join(u["empresas"])
        u["situacao"] = _situacao(u, agora)
    for coluna, marcados in filtros_coluna.items():
        if coluna in TIPOS_ORDENACAO_USUARIOS and marcados:
            aceitos = set(marcados)
            linhas = [
                u for u in linhas if (str(u.get(coluna) or "").strip() or SEM_VALOR) in aceitos
            ]
    if not ordenado:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO_USUARIOS, "login")


TIPOS_ORDENACAO_DIFERENCAS = {
    "empresa": "texto",
    "tipo": "texto",
    "mudanca": "texto",
    "descricao": "texto",
    "categoria": "texto",
    "efeito": "numero",
}


def diferencas_listagem(escopo, filtros_coluna: dict, ordenar=None, direcao="desc", ordenado=True):
    """Linhas que mudaram depois do fechamento da competência pedida (o
    parâmetro "competencia" da URL). Filtro e ordem em Python: são poucas."""
    from app import fechamento
    from app.ordenacao import ordenar_linhas
    from app.visao import SEM_VALOR

    competencia = (filtros_coluna.get("competencia") or [""])[0]
    dados = fechamento.diferencas(escopo, competencia)
    linhas = dados["diferencas"] if dados else []
    for coluna, marcados in filtros_coluna.items():
        if coluna in TIPOS_ORDENACAO_DIFERENCAS and marcados:
            aceitos = set(marcados)
            linhas = [
                d for d in linhas if (str(d.get(coluna) or "").strip() or SEM_VALOR) in aceitos
            ]
    if not ordenado:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO_DIFERENCAS, "efeito")


TIPOS_ORDENACAO_DRE = {
    "empresa": "texto",
    "tipo": "texto",
    "competencia": "competencia",
    "descricao": "texto",
    "categoria": "texto",
    "valor": "numero",
}


def dre_linhas_listagem(escopo, filtros_coluna: dict, ordenar=None, direcao="desc", ordenado=True):
    """As linhas que compõem um número da DRE (periodo + componente + bloco
    vêm da URL). Parâmetro torto = lista vazia, não erro."""
    from app import dre
    from app.ordenacao import ordenar_linhas
    from app.visao import SEM_VALOR

    def um(coluna):
        return (filtros_coluna.get(coluna) or [None])[0]

    try:
        linhas = dre.linhas_do_componente(
            escopo, filtros_coluna.get("periodo") or [], um("componente"), um("bloco")
        )
    except ValueError:
        linhas = []
    for coluna in ("empresa", "tipo", "descricao", "categoria"):
        marcados = filtros_coluna.get(coluna)
        if marcados:
            aceitos = set(marcados)
            linhas = [
                l for l in linhas if (str(l.get(coluna) or "").strip() or SEM_VALOR) in aceitos
            ]
    if not ordenado:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO_DRE, "valor")


TIPOS_ORDENACAO_ALERTAS = {
    "situacao": "texto",
    "tipo_rotulo": "texto",
    "empresa": "texto",
    "descricao": "texto",
    "competencia": "competencia",
    "valor": "numero",
}


def alertas_listagem(escopo, filtros_coluna: dict, ordenar=None, direcao="desc", ordenado=True):
    """Alertas de anomalia com os funis de cabeçalho. Sem ordenação pedida,
    vale a ordem do cálculo: ativos primeiro, por tipo, maior valor antes."""
    from app import alertas
    from app.ordenacao import ordenar_linhas
    from app.visao import SEM_VALOR, casa_data

    linhas = alertas.calcular(escopo)
    for coluna, marcados in filtros_coluna.items():
        if not marcados or coluna not in TIPOS_ORDENACAO_ALERTAS:
            continue
        aceitos = set(marcados)
        if coluna == "competencia":
            # Árvore Ano > Mês: a seleção chega colapsada ("2026", "08/2026").
            linhas = [a for a in linhas if casa_data(a["competencia"], aceitos)]
        else:
            linhas = [
                a for a in linhas if (str(a.get(coluna) or "").strip() or SEM_VALOR) in aceitos
            ]
    if not ordenado or not ordenar:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO_ALERTAS, "valor")


LISTAGEM = {
    "alertas": alertas_listagem,
    "dre_linhas": dre_linhas_listagem,
    "diferencas": diferencas_listagem,
    "usuarios": usuarios_listagem,
    "despesas": despesas,
    "receitas": receitas,
    "receitas_vendas": receitas_vendas,
    "receitas_servicos": receitas_servicos,
}


def linhas(escopo, tabela: str, filtros_coluna: dict) -> list[dict]:
    if tabela not in LISTAGEM:
        raise ValueError(f"tabela desconhecida: {tabela}")
    # A lista do funil não depende da ordem das linhas: pula a ordenação.
    return LISTAGEM[tabela](escopo, filtros_coluna, ordenado=False)
