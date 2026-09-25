"""Painel de pendências de dados (Fase 4.1) e alertas de anomalia (Fase 4.5).
Todos os perfis, dentro do escopo; dispensar/reativar alerta exige escrita."""

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from app import alertas, exportar, paineis, pendencias, validacao
from app.seguranca import escrita_necessaria

bp = Blueprint("pendencias", __name__)


@bp.route("/pendencias")
def painel():
    itens = pendencias.calcular(g.escopo)
    return render_template(
        "pendencias.html",
        secao="pendencias",
        itens=itens,
        abertas=sum(1 for p in itens if p.quantidade),
        anomalias=alertas.resumo(alertas.calcular(g.escopo)),
        tipos_alerta=alertas.TIPOS,
    )


@bp.route("/alertas")
def alertas_lista():
    contexto = paineis.alertas(g.escopo, request.args)
    if exportar.pedido(request.args):
        return exportar.enviar(
            g.escopo,
            "alertas",
            "Alertas de anomalia",
            [
                ("Alertas ativos", contexto["ativos"], "int"),
                ("Valor dos ativos", contexto["valor_ativo"], "moeda"),
            ],
            exportar.COLUNAS_ALERTAS,
            contexto["linhas"],
            contexto["filtros_coluna"],
        )
    return render_template(
        "alertas.html", secao="pendencias", erro=request.args.get("erro"), **contexto
    )


def _de_volta(**extra):
    """Volta à lista com os mesmos filtros: eles vêm na query string da
    própria URL do POST (montada pelo url_for do template), nunca de um campo
    livre — sem redirecionamento aberto."""
    args = {k: v for k, v in request.args.to_dict(flat=False).items() if k != "erro"}
    return redirect(url_for("pendencias.alertas_lista", **args, **extra))


@bp.route("/alertas/dispensar", methods=["POST"])
@escrita_necessaria
def dispensar():
    try:
        chave = validacao.texto(request.form.get("chave"), "Alerta", maximo=600)
        motivo = validacao.texto(request.form.get("motivo"), "Motivo", maximo=300)
        alertas.dispensar(g.escopo, chave, motivo)
    except alertas.AlertaNaoEncontrado:
        abort(404)
    except ValueError as e:  # inclui ErroValidacao
        return _de_volta(erro=str(e))
    return _de_volta()


@bp.route("/alertas/reativar", methods=["POST"])
@escrita_necessaria
def reativar():
    try:
        chave = validacao.texto(request.form.get("chave"), "Alerta", maximo=600)
        alertas.reativar(g.escopo, chave)
    except alertas.AlertaNaoEncontrado:
        abort(404)
    except ValueError as e:
        return _de_volta(erro=str(e))
    return _de_volta()
