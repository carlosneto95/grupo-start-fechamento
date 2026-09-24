"""Receitas: telas de Vendas e de Serviços, ajuste manual e marcação."""

import sqlite3

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from app import paineis
from app.receitas import definir_ajuste, definir_marcacao

bp = Blueprint("receitas", __name__)


def _tela(tabela: str, rota: str, titulo: str):
    """Vendas e Serviços são a mesma listagem com o tipo de nota fixo; o que
    muda é a chave de tabela dos funis. `rota` é o endpoint que os links de
    ordenação e o "limpar filtros" da tela usam."""
    contexto = paineis.receitas(request.args, tabela)
    return render_template("receitas.html", rota=rota, titulo=titulo, secao=tabela, **contexto)


@bp.route("/receitas")
def antigo():
    """Endereço da antiga tela única — vira redirecionamento para link salvo
    continuar funcionando."""
    return redirect(url_for("receitas.vendas", **request.args))


@bp.route("/receitas/vendas")
def vendas():
    return _tela("receitas_vendas", "receitas.vendas", "Receitas Vendas")


@bp.route("/receitas/servicos")
def servicos():
    return _tela("receitas_servicos", "receitas.servicos", "Receitas Serviços")


@bp.route("/receitas/ajustar", methods=["POST"])
def ajustar():
    """Edição manual de competência/categoria. O valor do ERP não é tocado —
    o ajuste vai para coluna própria."""
    d = request.get_json()
    try:
        existe = definir_ajuste(
            d["empresa"],
            d["tipo_nota"],
            d["id"],
            competencia=d.get("competencia"),
            categoria=d.get("categoria"),
        )
    except sqlite3.IntegrityError:
        # O CHECK do banco recusou o valor (ex.: competência 13/2026). Nada
        # foi gravado; a tela mostra o aviso no próprio campo.
        return jsonify({"ok": False, "erro": "valor inválido"}), 400
    if not existe:
        return jsonify({"ok": False, "erro": "nota não encontrada"}), 404
    return jsonify({"ok": True})


@bp.route("/receitas/marcar", methods=["POST"])
def marcar():
    """Override Considerar/Desconsiderar de uma nota. O dado do ERP não muda."""
    d = request.get_json()
    # considerar: true, false, ou null (volta ao padrão da situação da nota).
    if not definir_marcacao(d["empresa"], d["tipo_nota"], d["id"], d["considerar"]):
        return jsonify({"ok": False, "erro": "nota não encontrada"}), 404
    return jsonify({"ok": True})
