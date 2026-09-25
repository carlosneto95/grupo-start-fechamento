"""Análise de receitas por categoria × mês."""

from flask import Blueprint, g, render_template, request

from financeiro import paineis

bp = Blueprint("analise", __name__)


@bp.route("/analise-receitas")
def receitas():
    return render_template(
        "analise_receitas.html", **paineis.analise_receitas(g.escopo, request.args)
    )
