"""DRE gerencial por competência (Fase 4.3).

Colunas: os meses do ano (até o último com receita), o acumulado do ano e as
variações do mês de referência (o último) contra o mês anterior e contra o
mesmo mês do ano anterior. Linhas: receita, impostos, despesa direta, Adm I,
Adm II e resultado, por centro de custo (Vendas, Serviços, Sem classificação),
com o mesmo cálculo do Dashboard — cada mês passa pelo `separar()`.

Decisões:
  - ACUMULADO = soma dos meses, não um separar() do ano inteiro. O rateio
    anual dividiria o Adm de outro jeito, e a coluna deixaria de bater com a
    soma das colunas que estão na tela.
  - Ano anterior: só aparece se estiver na visão (ANO_MINIMO). Em 2026 a
    comparação a/a mostra "—" — o prompt pede "quando existir dado", e a regra
    do projeto é não mostrar competência anterior a 2026.
  - Todo número tem drill-down (`componente` + `bloco` + período), que leva às
    linhas que o compõem (financeiro/dre.py:linhas_do_componente).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from financeiro.centros_de_custo import (
    CATEGORIA_ADM_PROPRIA,
    CATEGORIAS_ADM_GERAL,
    SERVICOS,
    VENDAS,
    _classificar,
    separar,
)
from financeiro.dinheiro import ZERO
from financeiro.receitas import listar_notas
from financeiro.repositorio_contas_pagar import listar_contas
from financeiro.visao import ANO_MINIMO

BLOCOS = (("vendas", VENDAS), ("servicos", SERVICOS), ("sem_classificacao", "Sem classificação"))


@dataclass(frozen=True)
class LinhaDRE:
    chave: str
    rotulo: str
    nivel: int  # 0 = total do grupo; 1 = por centro de custo
    campo: str  # campo do separar(): receita, imposto, despesa, adm1, adm2, resultado
    bloco: str | None  # vendas / servicos / sem_classificacao; None = total
    sinal: int  # +1 soma no resultado, -1 subtrai (só para exibir o "(−)")
    componente: str | None  # drill-down: receita, despesa, adm_geral, adm_propria


def _linhas_estrutura() -> list[LinhaDRE]:
    """A estrutura da DRE, na ordem contábil."""
    e = []
    e.append(LinhaDRE("receita", "Receita", 0, "receita", None, 1, "receita"))
    for b, nome in BLOCOS:
        e.append(LinhaDRE(f"receita_{b}", nome, 1, "receita", b, 1, "receita"))
    e.append(LinhaDRE("imposto", "(−) Impostos calculados", 0, "imposto", None, -1, "receita"))
    for b, nome in BLOCOS[:2]:
        e.append(
            LinhaDRE(
                f"imposto_{b}",
                f"{nome} ({'14' if b == 'vendas' else '10'}%)",
                1,
                "imposto",
                b,
                -1,
                "receita",
            )
        )
    e.append(LinhaDRE("despesa", "(−) Despesa direta", 0, "despesa", None, -1, "despesa"))
    for b, nome in BLOCOS:
        e.append(LinhaDRE(f"despesa_{b}", nome, 1, "despesa", b, -1, "despesa"))
    e.append(LinhaDRE("adm1", "(−) Adm I — ADM GERAL", 0, "adm1", None, -1, "adm_geral"))
    e.append(LinhaDRE("adm2", "(−) Adm II — administrativo do centro", 0, "adm2", None, -1, None))
    for b, nome in BLOCOS[:2]:
        e.append(
            LinhaDRE(
                f"adm2_{b}",
                f"{nome} ({CATEGORIA_ADM_PROPRIA[nome]})",
                1,
                "adm2",
                b,
                -1,
                "adm_propria",
            )
        )
    e.append(LinhaDRE("resultado", "= Resultado", 0, "resultado", None, 1, None))
    for b, nome in BLOCOS:
        e.append(LinhaDRE(f"resultado_{b}", nome, 1, "resultado", b, 1, None))
    return e


ESTRUTURA = _linhas_estrutura()


def _valor(blocos: dict, linha: LinhaDRE):
    fonte = blocos["total"] if linha.bloco is None else blocos[linha.bloco]["totais"]
    return fonte.get(linha.campo) or ZERO


def _meses_do_ano(ano: int, ultimo_mes: int) -> list[str]:
    return [f"{m:02d}/{ano}" for m in range(1, ultimo_mes + 1)]


def _por_mes(escopo, ano: int, empresas) -> dict[str, dict]:
    """separar() de cada mês do ano, com uma leitura só de contas e de notas.
    O filtro "AAAA" casa todas as competências do ano (visao.casa_data)."""
    filtro = {"empresa": list(empresas)} if empresas else {}
    contas = listar_contas(escopo, filtro, competencias={str(ano)}, ordenado=False)
    notas = listar_notas(escopo, dict(filtro), competencias={str(ano)}, ordenado=False)
    contas_mes, notas_mes = defaultdict(list), defaultdict(list)
    for c in contas:
        if c["considerar_efetivo"]:
            contas_mes[c["competencia"]].append(c)
    for n in notas:
        if n["considerar_efetivo"]:
            notas_mes[n["competencia_efetiva"]].append(n)
    meses = set(contas_mes) | set(notas_mes)
    return {m: separar(notas_mes[m], contas_mes[m]) for m in meses}


def _ultimo_mes_com_receita(por_mes: dict, ano: int) -> int:
    meses = [
        int(m[:2]) for m, b in por_mes.items() if b["total"]["receita"] and m.endswith(str(ano))
    ]
    return max(meses) if meses else 0


def montar(escopo, ano: int, empresas=None, ate: int | None = None) -> dict:
    """A DRE do ano, pronta para o template.

    `ate` corta as colunas num mês (1-12): o último mês com receita costuma
    estar em andamento, e a variação m/m contra um mês parcial não diz nada.
    Escolhendo o mês de referência, as variações passam a ser dele."""
    por_mes = _por_mes(escopo, ano, empresas)
    ultimo = _ultimo_mes_com_receita(por_mes, ano)
    if ate:
        ultimo = min(ultimo, ate)
    meses = _meses_do_ano(ano, ultimo)
    vazio = separar([], [])

    anterior_visivel = ano - 1 >= ANO_MINIMO
    por_mes_anterior = _por_mes(escopo, ano - 1, empresas) if anterior_visivel else {}
    referencia = meses[-1] if meses else None
    mes_anterior = meses[-2] if len(meses) > 1 else None
    mesmo_mes_ano_anterior = f"{referencia[:2]}/{ano - 1}" if referencia else None

    linhas = []
    for linha in ESTRUTURA:
        valores = [_valor(por_mes.get(m, vazio), linha) for m in meses]
        ref = valores[-1] if valores else ZERO
        ant = valores[-2] if len(valores) > 1 else None
        aa = (
            _valor(por_mes_anterior.get(mesmo_mes_ano_anterior, vazio), linha)
            if anterior_visivel and mesmo_mes_ano_anterior in por_mes_anterior
            else None
        )
        linhas.append(
            {
                "def": linha,
                "valores": valores,
                "acumulado": sum(valores, ZERO),
                "var_mm": None if ant is None else ref - ant,
                "var_mm_pct": None if not ant else (ref - ant) / abs(ant) * 100,
                "var_aa": None if aa is None else ref - aa,
                "var_aa_pct": None if not aa else (ref - aa) / abs(aa) * 100,
            }
        )
    margem = [por_mes.get(m, vazio)["total"]["margem"] for m in meses]
    rec = next(l for l in linhas if l["def"].chave == "receita")["acumulado"]
    res = next(l for l in linhas if l["def"].chave == "resultado")["acumulado"]
    return {
        "ano": ano,
        "ultimo_com_receita": _ultimo_mes_com_receita(por_mes, ano),
        "meses": meses,
        "referencia": referencia,
        "mes_anterior": mes_anterior,
        "mesmo_mes_ano_anterior": mesmo_mes_ano_anterior if anterior_visivel else None,
        "linhas": linhas,
        "margem": margem,
        "margem_acumulada": (res / rec * 100) if rec else None,
    }


# ---- drill-down ------------------------------------------------------------------------

COMPONENTES = ("receita", "despesa", "adm_geral", "adm_propria")
BLOCOS_CHAVE = {b: nome for b, nome in BLOCOS}


def linhas_do_componente(escopo, periodo, componente: str, bloco: str | None, empresas=None):
    """As linhas (notas ou contas CONSIDERADAS) que compõem um número da DRE.

    `periodo` é "MM/AAAA" (um mês) ou "AAAA" (o acumulado do ano) — o mesmo
    formato que a árvore de competência entende (visao.casa_data) —, ou uma
    lista deles: o acumulado com mês de referência escolhido é jan..ref."""
    periodos = {periodo} if isinstance(periodo, str) else set(periodo)
    if not periodos or not all(periodos):
        raise ValueError("período vazio")
    if componente not in COMPONENTES:
        raise ValueError(f"componente inválido: {componente}")
    if bloco is not None and bloco not in BLOCOS_CHAVE:
        raise ValueError(f"bloco inválido: {bloco}")
    nome_bloco = BLOCOS_CHAVE.get(bloco)
    filtro = {"empresa": list(empresas)} if empresas else {}
    saida = []
    if componente == "receita":
        for n in listar_notas(escopo, dict(filtro), competencias=periodos, ordenado=False):
            if not n["considerar_efetivo"]:
                continue
            classe = _classificar(n["categoria_primaria_efetiva"]) or SERVICOS
            if nome_bloco and classe != nome_bloco:
                continue
            saida.append(
                {
                    "tipo": "nota de " + ("venda" if n["tipo_nota"] == "venda" else "serviço"),
                    "empresa": n["empresa"],
                    "competencia": n["competencia_efetiva"],
                    "documento": n["numero"] or "",
                    "descricao": n["cliente_nome"] or "",
                    "categoria": (n["categoria_primaria_efetiva"] or "").strip(),
                    "valor": n["valor"] or ZERO,
                }
            )
        return saida
    for c in listar_contas(escopo, filtro, competencias=periodos, ordenado=False):
        if not c["considerar_efetivo"]:
            continue
        categoria = (c["categoria_primaria"] or "").strip()
        nome = categoria.upper()
        if componente == "adm_geral":
            if nome not in CATEGORIAS_ADM_GERAL:
                continue
        elif componente == "adm_propria":
            if nome != CATEGORIA_ADM_PROPRIA.get(nome_bloco, "").upper():
                continue
        else:  # despesa direta do bloco: sem as categorias que viram Adm
            classe = _classificar(categoria)
            if not classe or (nome_bloco and classe != nome_bloco):
                continue
        saida.append(
            {
                "tipo": "conta a pagar",
                "empresa": c["empresa"],
                "competencia": c["competencia"],
                "documento": c["data_vencimento"] or "",
                "descricao": c["fornecedor"] or "",
                "categoria": categoria,
                "valor": c["valor"] or ZERO,
            }
        )
    return saida
