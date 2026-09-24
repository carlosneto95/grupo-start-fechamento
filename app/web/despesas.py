"""Despesas (contas a pagar): listagem e a marcação Considerar/Desconsiderar."""

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from app import paineis
from app.repositorio_contas_pagar import definir_manual

bp = Blueprint("despesas", __name__)


@bp.route("/despesas")
def listar():
    return render_template("despesas.html", **paineis.despesas(request.args))


@bp.route("/contas-pagar")
def contas_pagar_antigo():
    """Endereço anterior — mantido para não quebrar link salvo."""
    return redirect(url_for("despesas.listar", **request.args))


@bp.route("/despesas/marcar", methods=["POST"])
def marcar():
    dados = request.get_json()
    # considerar: true, false, ou null (volta para o padrão das regras).
    definir_manual(dados["empresa"], dados["id"], dados["considerar"])
    return jsonify({"ok": True})
