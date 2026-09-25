"""Despesas (contas a pagar): listagem e a marcação Considerar/Desconsiderar."""

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from app import exportar, paineis, validacao
from app.repositorio_contas_pagar import definir_manual
from app.seguranca import escrita_necessaria
from app.trava_fechamento import CompetenciaFechada

bp = Blueprint("despesas", __name__)


@bp.route("/despesas")
def listar():
    contexto = paineis.despesas(g.escopo, request.args)
    if exportar.pedido(request.args):
        # A planilha leva TODAS as linhas do recorte (contexto["contas"]), não
        # só as 2 mil desenhadas na tela.
        return exportar.enviar(
            g.escopo,
            "despesas",
            "Despesas — contas a pagar",
            [("Total considerado", contexto["total_considerado"], "moeda")],
            exportar.COLUNAS_DESPESAS,
            contexto["contas"],
            contexto["filtros_coluna"],
        )
    return render_template("despesas.html", **contexto)


@bp.route("/contas-pagar")
def contas_pagar_antigo():
    """Endereço anterior — mantido para não quebrar link salvo."""
    return redirect(url_for("despesas.listar", **request.args))


@bp.route("/despesas/marcar", methods=["POST"])
@escrita_necessaria
def marcar():
    dados = request.get_json(silent=True) or {}
    try:
        empresa = validacao.texto(dados.get("empresa"), "Empresa", maximo=40)
        id_conta = validacao.id_tiny(dados.get("id"))
        # true, false, ou null (volta para o padrão das regras de exclusão).
        considerar = validacao.booleano_ou_nulo(dados.get("considerar"))
    except validacao.ErroValidacao as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    # False = não existe OU fora do escopo: 404 nos dois casos (não confirma
    # a existência de conta de outra empresa).
    try:
        existe = definir_manual(g.escopo, empresa, id_conta, considerar)
    except CompetenciaFechada as e:
        return jsonify({"ok": False, "erro": str(e)}), 409
    if not existe:
        return jsonify({"ok": False, "erro": "conta não encontrada"}), 404
    return jsonify({"ok": True})
