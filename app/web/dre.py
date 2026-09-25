"""DRE gerencial (Fase 4.3) e o drill-down até as linhas. Todos os perfis,
dentro do escopo."""

from datetime import datetime

from flask import Blueprint, g, render_template, request

from app import dre, paineis
from app.db import FUSO_BRASILIA
from app.repositorio_contas_pagar import opcoes_de_filtro
from app.visao import ANO_MINIMO

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
    return render_template(
        "dre.html",
        secao="dre",
        dre=dre.montar(g.escopo, ano, empresas or None, ate),
        ate=ate,
        anos=anos,
        empresas_disponiveis=disponiveis,
        empresas=empresas,
    )


@bp.route("/dre/linhas")
def linhas():
    contexto = paineis.dre_linhas(g.escopo, request.args)
    return render_template(
        "dre_linhas.html",
        secao="dre",
        periodo=request.args.getlist("periodo"),
        componente=request.args.get("componente", ""),
        bloco=request.args.get("bloco", ""),
        **contexto,
    )
