"""Dashboard (Resultados) e a página inicial."""

from flask import Blueprint, redirect, render_template, request, url_for

from app import paineis

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def inicio():
    # A tela de trabalho do dia a dia é Despesas; o endereço raiz leva para lá.
    return redirect(url_for("despesas.listar"))


@bp.route("/dashboard")
def painel():
    return render_template("dashboard.html", **paineis.dashboard(request.args))
