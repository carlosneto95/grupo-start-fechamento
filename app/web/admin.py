"""Configurações: regras de exclusão por categoria/subcategoria."""

from flask import Blueprint, redirect, render_template, request, url_for

from app.repositorio_contas_pagar import (
    definir_regras_exclusao,
    listar_regras_exclusao,
    listar_valores_distintos,
)

bp = Blueprint("admin", __name__)


@bp.route("/configuracoes/exclusoes", methods=["GET", "POST"])
def exclusoes():
    if request.method == "POST":
        definir_regras_exclusao("categoria_primaria", request.form.getlist("categoria_primaria"))
        definir_regras_exclusao("subcategoria", request.form.getlist("subcategoria"))
        return redirect(url_for("admin.exclusoes"))

    regras = listar_regras_exclusao()
    return render_template(
        "configuracoes_exclusoes.html",
        categorias_primarias=listar_valores_distintos("categoria_primaria"),
        subcategorias=listar_valores_distintos("subcategoria"),
        categorias_excluidas=set(regras.get("categoria_primaria", [])),
        subcategorias_excluidas=set(regras.get("subcategoria", [])),
    )
