"""DRE gerencial (Fase 4.3) e o drill-down até as linhas. Todos os perfis,
dentro do escopo."""

from datetime import datetime

from flask import Blueprint, g, render_template, request

from financeiro import dre, exportar, paineis
from financeiro.db import FUSO_BRASILIA
from financeiro.repositorio_contas_pagar import opcoes_de_filtro
from financeiro.visao import ANO_MINIMO

bp = Blueprint("dre", __name__)


@bp.route("/dre")
def demonstrativo():
    atual = datetime.now(FUSO_BRASILIA).year
    anos = list(range(ANO_MINIMO, atual + 1))
    try:
        ano = int(request.args.get("ano") or atual)
    except ValueError:
        ano = atual
    if ano not in anos:
        ano = atual
    # Empresa: só as que o escopo enxerga (lista branca = as opções do escopo).
    disponiveis = opcoes_de_filtro(g.escopo)["empresa"]
    empresas = [e for e in request.args.getlist("empresa") if e in disponiveis]
    # Mês de referência (corte das colunas); inválido = até o último com receita.
    try:
        ate = int(request.args.get("ate") or 0)
    except ValueError:
        ate = 0
    ate = ate if 1 <= ate <= 12 else None
    montado = dre.montar(g.escopo, ano, empresas or None, ate)
    if exportar.pedido(request.args):
        resultado = next(l for l in montado["linhas"] if l["def"].chave == "resultado")
        return exportar.enviar(
            g.escopo,
            f"dre_{ano}",
            f"DRE gerencial {ano}",
            [
                ("Empresas", ", ".join(empresas) or "todas do seu acesso", "texto"),
                ("Mês de referência", montado["referencia"] or "—", "texto"),
                ("Resultado acumulado", resultado["acumulado"], "moeda"),
                ("Margem acumulada", montado["margem_acumulada"], "pct"),
            ],
            exportar.colunas_dre(montado["meses"]),
            montado["linhas"],
            {"empresa": empresas} if empresas else None,
        )
    return render_template(
        "dre.html",
        secao="dre",
        dre=montado,
        ate=ate,
        anos=anos,
        empresas_disponiveis=disponiveis,
        empresas=empresas,
    )


@bp.route("/dre/linhas")
def linhas():
    contexto = paineis.dre_linhas(g.escopo, request.args)
    periodos = request.args.getlist("periodo")
    if exportar.pedido(request.args):
        componente = request.args.get("componente", "")
        bloco = request.args.get("bloco") or ""
        faixa = f"{periodos[0]} a {periodos[-1]}" if len(periodos) > 1 else "".join(periodos)
        return exportar.enviar(
            g.escopo,
            "dre_detalhe",
            f"DRE — detalhe: {componente} {bloco} · {faixa}".replace("  ", " "),
            [("Total", contexto["total"], "moeda")],
            exportar.COLUNAS_DRE_LINHAS,
            contexto["linhas"],
            contexto["filtros_coluna"],
        )
    return render_template(
        "dre_linhas.html",
        secao="dre",
        periodo=periodos,
        componente=request.args.get("componente", ""),
        bloco=request.args.get("bloco", ""),
        **contexto,
    )
