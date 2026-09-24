"""Monta o que cada tela mostra, a partir dos filtros da URL.

As rotas (app/web/) ficam finas: leem a requisição, chamam uma função daqui e
entregam o resultado ao template. Toda a regra — que filtro vale, o que entra
no total, como o dashboard confronta receita e despesa — mora aqui, onde dá
para testar sem subir servidor.

Cada função recebe `args` (o MultiDict da query string, ou qualquer objeto
com .get/.getlist/.to_dict) e devolve o dicionário de contexto do template.
Nada aqui foi recalculado de outro jeito na Fase 1: é o mesmo código que
estava em app.py, só mudou de endereço — o golden master confere.
"""

from __future__ import annotations

from datetime import date

from app import consulta
from app.analise_receitas import grades
from app.centros_de_custo import separar as separar_centros_de_custo
from app.filtros_coluna import COLUNAS as COLUNAS_FILTRAVEIS
from app.filtros_coluna import valores as valores_de_coluna
from app.ordenacao import coluna_e_direcao, ordenar_linhas
from app.receitas import COLUNAS_ORDENAVEIS as COLUNAS_ORDENAVEIS_NOTAS
from app.receitas import categorias_conhecidas, listar_notas
from app.repositorio_contas_pagar import (
    COLUNAS_ORDENAVEIS,
    competencias_disponiveis,
    listar_contas,
    listar_valores_distintos,
)
from app.resumos import TIPOS_ORDENACAO_RESULTADO, arvore_de_gastos
from app.visao import ANO_MINIMO

COLUNAS_FILTRO_DESPESAS = list(COLUNAS_FILTRAVEIS["despesas"])

# Teto de linhas desenhadas na tela de Despesas sem "mostrar todas". 2 mil
# cobre com folga um mês inteiro das três empresas (~1.300 lançamentos).
LINHAS_NA_TELA = 2000


def _filtros_da_url(args, colunas) -> dict:
    """Filtros de coluna vindos da URL: cada coluna manda seus valores marcados
    repetidos, ex: ?fornecedor=A&fornecedor=B. Coluna sem valor fica de fora."""
    marcados = {c: [v for v in args.getlist(c) if v] for c in colunas}
    return {c: v for c, v in marcados.items() if v}


def _multi(args, nome) -> list[str]:
    """Slicer de seleção múltipla: vem como lista repetida na URL."""
    return [v for v in args.getlist(nome) if v]


# --------------------------------------------------------------------------
# Despesas
# --------------------------------------------------------------------------


def despesas(args) -> dict:
    filtros_coluna = _filtros_da_url(args, COLUNAS_FILTRO_DESPESAS)

    ordenar = args.get("ordenar") or "data_vencimento"
    if ordenar not in COLUNAS_ORDENAVEIS:
        ordenar = "data_vencimento"
    direcao = "desc" if args.get("direcao") == "desc" else "asc"

    contas = consulta.despesas(filtros_coluna, ordenar=ordenar, direcao=direcao)
    # A tela desenha no máximo LINHAS_NA_TELA linhas; "mostrar todas" (?todas=1)
    # tira o limite. Totais, contagem e funis continuam sobre TODAS as linhas
    # do recorte — só o HTML fica menor. Decisão do Neto (Fase 1): renderizar
    # 15 mil linhas custava ~300 ms e 12 MB por abertura da tela.
    todas = args.get("todas") == "1"
    exibidas = contas if todas else contas[:LINHAS_NA_TELA]
    return {
        "contas": contas,
        "contas_exibidas": exibidas,
        "mostrando_todas": todas,
        "linhas_ocultas": len(contas) - len(exibidas),
        "total_considerado": sum(c["valor"] or 0 for c in contas if c["considerar_efetivo"]),
        "ordenar": ordenar,
        "direcao": direcao,
        "filtros_coluna": filtros_coluna,
        # flat=False preserva os valores repetidos dos filtros de coluna ao
        # remontar links de ordenação.
        "args_atuais": args.to_dict(flat=False),
    }


# --------------------------------------------------------------------------
# Receitas (Vendas e Serviços)
# --------------------------------------------------------------------------


def receitas(args, tabela: str) -> dict:
    """As telas de Vendas e de Serviços são a mesma listagem com o tipo de nota
    fixo; o que muda é a chave de tabela usada pelos funis (filtros_coluna.py)."""
    filtros_coluna = _filtros_da_url(args, COLUNAS_FILTRAVEIS[tabela])

    ordenar = args.get("ordenar") or "data_emissao"
    if ordenar not in COLUNAS_ORDENAVEIS_NOTAS:
        ordenar = "data_emissao"
    direcao = "asc" if args.get("direcao") == "asc" else "desc"

    notas = consulta.LISTAGEM[tabela](filtros_coluna, ordenar=ordenar, direcao=direcao)
    faturadas = [n for n in notas if n["considerar_efetivo"]]
    return {
        "tabela": tabela,
        "notas": notas,
        "total_receita": sum(n["valor"] or 0 for n in faturadas),
        "total_excluido": sum(n["valor"] or 0 for n in notas if not n["considerar_efetivo"]),
        "quantidade": len(faturadas),
        "excluidas": len(notas) - len(faturadas),
        "filtros_coluna": filtros_coluna,
        "categorias_sugeridas": categorias_conhecidas(),
        "ordenar": ordenar,
        "direcao": direcao,
        "args_atuais": args.to_dict(flat=False),
    }


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


def periodo_padrao_dashboard(hoje: date | None = None) -> dict:
    """Competências de 01/ANO_MINIMO até o último mês com RECEITA considerada.

    A receita define o fim porque é ela que para quando o mês ainda não foi
    faturado; a despesa tem parcela lançada anos à frente. Sem nenhuma nota,
    o fim é o mês corrente."""
    hoje = hoje or date.today()
    fim = (hoje.year, hoje.month)
    meses = [
        (int(c[3:]), int(c[:2]))
        for c in (n["competencia_efetiva"] for n in listar_notas({}) if n["considerar_efetivo"])
        if c and len(c) == 7 and c[:2].isdigit() and c[3:].isdigit() and 1 <= int(c[:2]) <= 12
    ]
    if meses:
        fim = max(meses)
    competencias = []
    ano, mes = ANO_MINIMO, 1
    while (ano, mes) <= fim:
        competencias.append(f"{mes:02d}/{ano}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return {
        "inicio": competencias[0] if competencias else None,
        "fim": competencias[-1] if competencias else None,
        "competencias": competencias,
    }


def dashboard(args) -> dict:
    """Slicers à esquerda, árvore de gastos no meio e os quadros de resultado
    (Total, Vendas, Serviços) à direita."""
    filtros = {
        "empresa": _multi(args, "empresa"),
        "categoria_primaria": _multi(args, "categoria_primaria"),
        "subcategoria": _multi(args, "subcategoria"),
    }
    # Competência também é slicer aqui. Nada marcado NÃO significa mais
    # "todas" (decisão do Neto, Fase 1): o Total somava parcelas lançadas até
    # 2032 contra uma receita que para no último mês faturado, e não era
    # resultado de período nenhum. Sem seleção, vale o período padrão —
    # de 01/ANO_MINIMO ao último mês com receita — escrito no cabeçalho.
    competencias_marcadas = _multi(args, "competencia")
    periodo_padrao = None if competencias_marcadas else periodo_padrao_dashboard()
    competencias_sel = (
        set(competencias_marcadas) if competencias_marcadas else set(periodo_padrao["competencias"])
    )

    # As colunas do banco vão em `filtros`; a competência é tratada à parte
    # porque as notas guardam a delas noutra coluna (com o ajuste manual).
    # ordenado=False: o Dashboard só AGREGA as contas; ordenar 15 mil linhas
    # por vencimento para depois somar era custo puro.
    contas = listar_contas(
        {k: v for k, v in filtros.items() if v}, competencias=competencias_sel, ordenado=False
    )
    filtros["competencia"] = competencias_marcadas  # só para o template marcar os itens
    consideradas = [c for c in contas if c["considerar_efetivo"]]

    # Receita acompanha empresa e competência; categoria/subcategoria da despesa
    # não se aplicam às notas, que têm vocabulário próprio de categoria.
    notas = listar_notas(
        {"empresa": filtros["empresa"]} if filtros["empresa"] else {},
        competencias=competencias_sel,
    )
    faturadas = [n for n in notas if n["considerar_efetivo"]]

    total_receita = sum(n["valor"] or 0 for n in faturadas)
    total_despesa = sum(c["valor"] or 0 for c in consideradas)

    ordenar_tabela, direcao_tabela = coluna_e_direcao(
        {"ordenar": args.get("ordenar_tabela"), "direcao": args.get("direcao_tabela")},
        TIPOS_ORDENACAO_RESULTADO,
        "movimento",
        "desc",
    )

    # Vendas x Serviços, com o ADM GERAL rateado entre os dois. A ordenação do
    # cabeçalho vale para os dois quadros de uma vez — são a mesma tabela
    # partida em dois, não faria sentido ordenar cada uma por um critério.
    def ordenada(linhas):
        return ordenar_linhas(
            linhas, ordenar_tabela, direcao_tabela, TIPOS_ORDENACAO_RESULTADO, "movimento"
        )

    blocos = separar_centros_de_custo(faturadas, consideradas)
    blocos["vendas"]["linhas"] = ordenada(blocos["vendas"]["linhas"])
    blocos["servicos"]["linhas"] = ordenada(blocos["servicos"]["linhas"])

    return {
        "secao": "dashboard",
        "arvore": arvore_de_gastos(consideradas),
        "blocos": blocos,
        "ordenar_tabela": ordenar_tabela,
        "direcao_tabela": direcao_tabela,
        "total_receita": total_receita,
        "total_despesa": total_despesa,
        "resultado": total_receita - total_despesa,
        "margem": ((total_receita - total_despesa) / total_receita * 100) if total_receita else 0,
        "periodo_padrao": periodo_padrao,
        "quantidade_notas": len(faturadas),
        "quantidade_contas": len(consideradas),
        "filtros": filtros,
        "opcoes": {
            "competencia": competencias_disponiveis(),
            "empresa": listar_valores_distintos("empresa"),
            "categoria_primaria": listar_valores_distintos("categoria_primaria"),
            "subcategoria": listar_valores_distintos("subcategoria"),
        },
        "args_atuais": args.to_dict(flat=False),
    }


# --------------------------------------------------------------------------
# Análise de receitas
# --------------------------------------------------------------------------


def analise_receitas(args) -> dict:
    """Faturamento com a categoria como espinha dorsal. Ao contrário do
    Dashboard, não entra despesa nem rateio: a pergunta é de onde vem o
    dinheiro e em que mês ele parou de vir."""
    competencias_marcadas = _multi(args, "competencia")
    tipos_marcados = _multi(args, "tipo_nota")
    categorias_marcadas = _multi(args, "categoria_primaria_efetiva")

    notas = listar_notas(
        {"tipo_nota": tipos_marcados} if tipos_marcados else {},
        competencias=set(competencias_marcadas) or None,
        categorias=set(categorias_marcadas) or None,
    )
    faturadas = [n for n in notas if n["considerar_efetivo"]]

    # As opções dos slicers saem do universo INTEIRO, não do recorte filtrado:
    # os slicers do dashboard não cascateiam (decisão de 24/08/2026), e sem isso
    # marcar uma categoria apagaria as outras da lista.
    todas = [n for n in listar_notas({}) if n["considerar_efetivo"]]

    return {
        "secao": "analise_receitas",
        "grade": grades(faturadas),
        "filtros": {
            "competencia": competencias_marcadas,
            "tipo_nota": tipos_marcados,
            "categoria_primaria_efetiva": categorias_marcadas,
        },
        "opcoes": {
            "competencia": sorted(
                {n["competencia_efetiva"] for n in todas if n["competencia_efetiva"]},
                key=lambda c: (c[3:], c[:2]),
            ),
            "tipo_nota": sorted({n["tipo_nota"] for n in todas if n["tipo_nota"]}),
            "categoria_primaria_efetiva": sorted(
                {
                    (n["categoria_primaria_efetiva"] or "").strip()
                    for n in todas
                    if (n["categoria_primaria_efetiva"] or "").strip()
                }
            ),
        },
    }


# --------------------------------------------------------------------------
# Lista do funil de coluna (AJAX)
# --------------------------------------------------------------------------


def valores_filtro(args) -> tuple[dict, int]:
    """Lista de um funil, em cascata como no Excel: os valores saem das linhas
    que sobrevivem aos filtros das OUTRAS colunas. O filtro da própria coluna
    é retirado de propósito — senão, ao marcar um valor, a lista passaria a ter
    só ele e nunca mais daria para acrescentar outro.

    Devolve (corpo, status_http)."""
    tabela = args.get("tabela", "")
    coluna = args.get("coluna", "")
    if tabela not in COLUNAS_FILTRAVEIS:
        return {"erro": f"tabela desconhecida: {tabela}"}, 400

    filtros_coluna = _filtros_da_url(args, COLUNAS_FILTRAVEIS[tabela])
    selecionados = filtros_coluna.pop(coluna, [])
    try:
        dados = valores_de_coluna(
            tabela,
            coluna,
            consulta.linhas(tabela, filtros_coluna),
            (args.get("q") or "").strip(),
            selecionados,
        )
    except ValueError as e:
        return {"erro": str(e)}, 400
    return dados, 200
