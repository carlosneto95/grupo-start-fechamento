"""Receitas: telas de Vendas e de Serviços, ajuste manual e marcação."""

import sqlite3

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from financeiro import exportar, paineis, validacao
from financeiro.receitas import definir_ajuste, definir_marcacao
from financeiro.seguranca import escrita_necessaria
from financeiro.trava_fechamento import CompetenciaFechada

bp = Blueprint("receitas", __name__)

TIPOS_NOTA = ("venda", "servico")


def _tela(tabela: str, rota: str, titulo: str):
    """Vendas e Serviços são a mesma listagem com o tipo de nota fixo; o que
    muda é a chave de tabela dos funis. `rota` é o endpoint que os links de
    ordenação e o "limpar filtros" da tela usam."""
    contexto = paineis.receitas(g.escopo, request.args, tabela)
    if exportar.pedido(request.args):
        return exportar.enviar(
            g.escopo,
            tabela,
            titulo,
            [
                ("Receita considerada", contexto["total_receita"], "moeda"),
                ("Notas consideradas", contexto["quantidade"], "int"),
                ("Desconsiderado", contexto["total_excluido"], "moeda"),
                ("Notas desconsideradas", contexto["excluidas"], "int"),
            ],
            exportar.COLUNAS_NOTAS,
            contexto["notas"],
            contexto["filtros_coluna"],
        )
    return render_template("receitas.html", rota=rota, titulo=titulo, secao=tabela, **contexto)


def _chave_da_nota(d: dict) -> tuple[str, str, str]:
    return (
        validacao.texto(d.get("empresa"), "Empresa", maximo=40),
        validacao.escolha(d.get("tipo_nota"), "Tipo de nota", TIPOS_NOTA),
        validacao.id_tiny(d.get("id")),
    )


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
@escrita_necessaria
def ajustar():
    """Edição manual de competência/categoria. O valor do ERP não é tocado —
    o ajuste vai para coluna própria."""
    d = request.get_json(silent=True) or {}
    try:
        empresa, tipo, id_nota = _chave_da_nota(d)
        # Campo ausente = não mexe; string vazia = limpa o ajuste.
        competencia = None if "competencia" not in d else validacao.competencia(d["competencia"])
        categoria = (
            None
            if "categoria" not in d
            else validacao.texto(d["categoria"], "Categoria", maximo=80, obrigatorio=False)
        )
        existe = definir_ajuste(
            g.escopo, empresa, tipo, id_nota, competencia=competencia, categoria=categoria
        )
    except validacao.ErroValidacao as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    except sqlite3.IntegrityError:
        # Segunda barreira: o CHECK do banco recusou. Nada foi gravado.
        return jsonify({"ok": False, "erro": "valor inválido"}), 400
    except CompetenciaFechada as e:
        return jsonify({"ok": False, "erro": str(e)}), 409
    if not existe:
        return jsonify({"ok": False, "erro": "nota não encontrada"}), 404
    return jsonify({"ok": True})


@bp.route("/receitas/marcar", methods=["POST"])
@escrita_necessaria
def marcar():
    """Override Considerar/Desconsiderar de uma nota. O dado do ERP não muda."""
    d = request.get_json(silent=True) or {}
    try:
        empresa, tipo, id_nota = _chave_da_nota(d)
        # true, false, ou null (volta ao padrão da situação da nota).
        considerar = validacao.booleano_ou_nulo(d.get("considerar"))
    except validacao.ErroValidacao as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    try:
        existe = definir_marcacao(g.escopo, empresa, tipo, id_nota, considerar)
    except CompetenciaFechada as e:
        return jsonify({"ok": False, "erro": str(e)}), 409
    if not existe:
        return jsonify({"ok": False, "erro": "nota não encontrada"}), 404
    return jsonify({"ok": True})
