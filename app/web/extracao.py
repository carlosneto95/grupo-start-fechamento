"""Sincronização com o Tiny disparada pela tela."""

from datetime import date

from flask import Blueprint, jsonify, render_template, request

from app import sincronizar_tudo
from app.config.companies import load_companies
from app.extracao_job import estado_atual, iniciar as iniciar_job

bp = Blueprint("extracao", __name__)


@bp.route("/extracao")
def tela():
    hoje = date.today()
    return render_template(
        "extracao.html",
        empresas=load_companies(),
        anos=list(range(hoje.year - 3, hoje.year + 2)),
        ano_atual=hoje.year,
        ultimas=sincronizar_tudo.ultimas(),
    )


@bp.route("/extracao/iniciar", methods=["POST"])
def iniciar():
    dados = request.get_json()
    ok, mensagem = iniciar_job(
        dados.get("empresa"), int(dados.get("ano")), forcar=bool(dados.get("forcar"))
    )
    return jsonify({"ok": ok, "mensagem": mensagem}), (200 if ok else 409)


@bp.route("/extracao/status")
def status():
    return jsonify(estado_atual())
