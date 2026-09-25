"""Fechamento de competência (Fase 4.2): lista dos meses, diferenças pós-
fechamento (todos os perfis, dentro do escopo), fechar e reabrir (só Admin)."""

from flask import Blueprint, g, redirect, render_template, request, url_for

from app import exportar, fechamento, paineis, validacao
from app.seguranca import admin_necessario

bp = Blueprint("fechamento", __name__)


def _lista(erro: str | None = None, status: int = 200):
    vigentes = fechamento.vigentes()
    alertas = {a["competencia"]: a for a in fechamento.alertas(g.escopo, set(vigentes))}
    meses = [
        {"competencia": c, "fechamento": vigentes.get(c), "alerta": alertas.get(c)}
        for c in fechamento.competencias_fechaveis()
    ]
    return render_template("fechamento.html", secao="fechamento", meses=meses, erro=erro), status


@bp.route("/fechamento")
def lista():
    return _lista()


@bp.route("/fechamento/fechar", methods=["POST"])
@admin_necessario
def fechar():
    try:
        competencia = validacao.competencia(request.form.get("competencia"), vazio_permitido=False)
        # Confirmação no próprio formulário (nada de confirm() do navegador).
        if request.form.get("confirmo") != "1":
            raise validacao.ErroValidacao(f"Marque a confirmação para fechar {competencia}.")
        fechamento.fechar(g.escopo, competencia)
    except (validacao.ErroValidacao, fechamento.ErroFechamento) as e:
        return _lista(str(e), 400)
    return redirect(url_for("fechamento.lista"))


@bp.route("/fechamento/diferencas")
def diferencas():
    try:
        competencia = validacao.competencia(request.args.get("competencia"), vazio_permitido=False)
    except validacao.ErroValidacao:
        return redirect(url_for("fechamento.lista"))
    dados = fechamento.diferencas(g.escopo, competencia)
    if dados is None:  # competência aberta: não há o que comparar
        return redirect(url_for("fechamento.lista"))
    tabela = paineis.diferencas_tabela(g.escopo, request.args)
    if exportar.pedido(request.args):
        # Resumo: o resultado no fechamento e agora, como no quadro da tela.
        resumo = [
            (f"{rotulo} — {quando}", dados[lado][campo], "moeda")
            for lado, quando in (("no_fechamento", "no fechamento"), ("agora", "agora"))
            for campo, rotulo in (("receita", "Receita"), ("resultado", "Resultado"))
        ]
        return exportar.enviar(
            g.escopo,
            f"diferencas_{competencia.replace('/', '-')}",
            f"Diferenças pós-fechamento — {competencia}",
            resumo,
            exportar.COLUNAS_DIFERENCAS,
            tabela["linhas"],
            tabela["filtros_coluna"],
        )
    return render_template(
        "fechamento_diferencas.html",
        secao="fechamento",
        competencia=competencia,
        dados=dados,
        historico=fechamento.historico(competencia),
        erro=request.args.get("erro"),
        **tabela,
    )


@bp.route("/fechamento/reabrir", methods=["POST"])
@admin_necessario
def reabrir():
    try:
        competencia = validacao.competencia(request.form.get("competencia"), vazio_permitido=False)
        motivo = validacao.texto(request.form.get("motivo"), "Motivo", maximo=300)
        fechamento.reabrir(g.escopo, competencia, motivo)
    except (validacao.ErroValidacao, fechamento.ErroFechamento) as e:
        return redirect(
            url_for(
                "fechamento.diferencas", competencia=request.form.get("competencia"), erro=str(e)
            )
        )
    return redirect(url_for("fechamento.lista"))
