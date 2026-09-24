"""Painel de pendências de dados (Fase 4.1). Todos os perfis, dentro do escopo."""

from flask import Blueprint, g, render_template

from app import pendencias

bp = Blueprint("pendencias", __name__)


@bp.route("/pendencias")
def painel():
    itens = pendencias.calcular(g.escopo)
    return render_template(
        "pendencias.html",
        secao="pendencias",
        itens=itens,
        abertas=sum(1 for p in itens if p.quantidade),
    )
