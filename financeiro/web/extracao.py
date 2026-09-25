"""Sincronização com o Tiny disparada pela tela — só Admin (consome a cota da
API das três contas)."""

from datetime import date

from flask import Blueprint, jsonify, render_template, request

from financeiro import sincronizar_tudo, validacao
from financeiro.config.companies import load_companies
from financeiro.extracao_job import TODAS, estado_atual
from financeiro.extracao_job import iniciar as iniciar_job
from financeiro.seguranca import admin_necessario

bp = Blueprint("extracao", __name__)


@bp.route("/extracao")
@admin_necessario
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
@admin_necessario
def iniciar():
    dados = request.get_json(silent=True) or {}
    try:
        chaves = [TODAS] + [e.key for e in load_companies()]
        empresa = validacao.escolha(dados.get("empresa"), "Empresa", chaves)
        ano = validacao.ano(dados.get("ano"))
        forcar = validacao.booleano_ou_nulo(dados.get("forcar")) or False
    except validacao.ErroValidacao as e:
        return jsonify({"ok": False, "mensagem": str(e)}), 400
    ok, mensagem = iniciar_job(empresa, ano, forcar=forcar)
    return jsonify({"ok": ok, "mensagem": mensagem}), (200 if ok else 409)


@bp.route("/extracao/status")
@admin_necessario
def status():
    return jsonify(estado_atual())
