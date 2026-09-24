"""Ponto de entrada do dashboard Flask."""
from datetime import date

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app import consulta
from app.config.companies import load_companies
from app.db import init_db
from app.extracao_job import estado_atual, iniciar
from app.filtros_coluna import COLUNAS as COLUNAS_FILTRAVEIS
from app.filtros_coluna import valores as valores_de_coluna
from app.receitas import (
    categorias_conhecidas,
    definir_ajuste,
    definir_marcacao,
    listar_notas,
)
from app.receitas import COLUNAS_ORDENAVEIS as COLUNAS_ORDENAVEIS_NOTAS
from app.ordenacao import coluna_e_direcao, ordenar_linhas
from app.visao import formatar_valor
from app.centros_de_custo import separar as separar_centros_de_custo
from app.analise_receitas import grades
from app.resumos import TIPOS_ORDENACAO_RESULTADO, arvore_de_gastos
from app.repositorio_contas_pagar import (
    COLUNAS_ORDENAVEIS,
    competencias_disponiveis,
    definir_manual,
    definir_regras_exclusao,
    listar_contas,
    listar_regras_exclusao,
    listar_valores_distintos,
)

COLUNAS_FILTRO_DESPESAS = list(COLUNAS_FILTRAVEIS["despesas"])

app = Flask(__name__)
init_db()


@app.template_filter("moeda")
def _moeda(valor) -> str:
    return formatar_valor(valor)


@app.route("/")
def index():
    return redirect(url_for("despesas"))


def _filtros_da_url(colunas) -> dict:
    """Filtros de coluna vindos da URL: cada coluna manda seus valores marcados
    repetidos, ex: ?fornecedor=A&fornecedor=B. Coluna sem valor fica de fora."""
    marcados = {c: [v for v in request.args.getlist(c) if v] for c in colunas}
    return {c: v for c, v in marcados.items() if v}


def _contexto_de_filtros():
    """Lê os filtros da URL e devolve (contas_filtradas, contexto_para_o_template).

    Compartilhado entre a listagem e o dashboard: as duas telas usam exatamente os
    mesmos filtros, então o recorte precisa ser calculado no mesmo lugar."""
    filtros_coluna = _filtros_da_url(COLUNAS_FILTRO_DESPESAS)

    ordenar = request.args.get("ordenar") or "data_vencimento"
    if ordenar not in COLUNAS_ORDENAVEIS:
        ordenar = "data_vencimento"
    direcao = "desc" if request.args.get("direcao") == "desc" else "asc"

    contas = consulta.despesas(filtros_coluna, ordenar=ordenar, direcao=direcao)

    contexto = {
        "ordenar": ordenar,
        "direcao": direcao,
        "filtros_coluna": filtros_coluna,
        # flat=False preserva os valores repetidos dos filtros de coluna ao
        # remontar links de ordenação.
        "args_atuais": request.args.to_dict(flat=False),
    }
    return contas, contexto


@app.route("/api/valores-filtro")
def api_valores_filtro():
    """Alimenta a lista do filtro de coluna, carregada só quando o funil abre.

    Em cascata, como no Excel: os valores saem das linhas que sobrevivem aos
    filtros das OUTRAS colunas. O filtro da própria coluna é retirado de
    propósito — senão, ao marcar um valor, a lista passaria a ter só ele e nunca
    mais daria para acrescentar outro."""
    tabela = request.args.get("tabela", "")
    coluna = request.args.get("coluna", "")
    if tabela not in COLUNAS_FILTRAVEIS:
        return jsonify({"erro": f"tabela desconhecida: {tabela}"}), 400

    filtros_coluna = _filtros_da_url(COLUNAS_FILTRAVEIS[tabela])
    selecionados = filtros_coluna.pop(coluna, [])

    try:
        dados = valores_de_coluna(
            tabela, coluna,
            consulta.linhas(tabela, filtros_coluna),
            (request.args.get("q") or "").strip(),
            selecionados,
        )
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify(dados)


@app.route("/contas-pagar")
def contas_pagar_antigo():
    """Endereço anterior — mantido para não quebrar link salvo."""
    return redirect(url_for("despesas", **request.args))


@app.route("/despesas")
def despesas():
    contas, contexto = _contexto_de_filtros()
    total_considerado = sum(c["valor"] or 0 for c in contas if c["considerar_efetivo"])
    return render_template(
        "despesas.html",
        contas=contas,
        total_considerado=total_considerado,
        **contexto,
    )


@app.route("/dashboard")
def dashboard():
    """Visão de análise: slicers à esquerda, árvore de gastos no meio, e à
    direita os três quadros de resultado (Total, Vendas, Serviços)."""
    def multi(nome):
        """Slicer de seleção múltipla: vem como lista repetida na URL."""
        return [v for v in request.args.getlist(nome) if v]

    filtros = {
        "empresa": multi("empresa"),
        "categoria_primaria": multi("categoria_primaria"),
        "subcategoria": multi("subcategoria"),
    }
    # Competência também é slicer aqui: nada marcado significa todas.
    competencias_marcadas = multi("competencia")
    competencias_sel = set(competencias_marcadas) or None

    # As colunas do banco vão em `filtros`; a competência é tratada à parte
    # porque as notas guardam a delas noutra coluna (com o ajuste manual).
    contas = listar_contas(
        {k: v for k, v in filtros.items() if v},
        competencias=competencias_sel,
    )
    filtros["competencia"] = competencias_marcadas  # só para o template marcar os itens
    consideradas = [c for c in contas if c["considerar_efetivo"]]

    # Receita acompanha empresa e competência; categoria/subcategoria da despesa
    # não se aplicam às notas, que têm vocabulário próprio de categoria.
    notas = listar_notas(
        {"empresa": filtros["empresa"]} if filtros["empresa"] else {},
        competencias=competencias_sel,
    )
    faturadas = [n for n in notas if n["considerar_efetivo"]]

    total_receita = sum(n["valor"] or 0 for n in faturadas)
    total_despesa = sum(c["valor"] or 0 for c in consideradas)

    ordenar_tabela, direcao_tabela = coluna_e_direcao(
        {"ordenar": request.args.get("ordenar_tabela"),
         "direcao": request.args.get("direcao_tabela")},
        TIPOS_ORDENACAO_RESULTADO, "movimento", "desc",
    )

    # Vendas x Serviços, com o ADM GERAL rateado entre os dois. A ordenação do
    # cabeçalho vale para os dois quadros de uma vez — são a mesma tabela
    # partida em dois, não faria sentido ordenar cada uma por um critério.
    def ordenada(linhas):
        return ordenar_linhas(linhas, ordenar_tabela, direcao_tabela,
                              TIPOS_ORDENACAO_RESULTADO, "movimento")

    blocos = separar_centros_de_custo(faturadas, consideradas)
    blocos["vendas"]["linhas"] = ordenada(blocos["vendas"]["linhas"])
    blocos["servicos"]["linhas"] = ordenada(blocos["servicos"]["linhas"])

    return render_template(
        "dashboard.html",
        secao="dashboard",
        arvore=arvore_de_gastos(consideradas),
        blocos=blocos,
        ordenar_tabela=ordenar_tabela,
        direcao_tabela=direcao_tabela,
        total_receita=total_receita,
        total_despesa=total_despesa,
        resultado=total_receita - total_despesa,
        margem=((total_receita - total_despesa) / total_receita * 100) if total_receita else 0,
        quantidade_notas=len(faturadas),
        quantidade_contas=len(consideradas),
        filtros=filtros,
        opcoes={
            "competencia": competencias_disponiveis(),
            "empresa": listar_valores_distintos("empresa"),
            "categoria_primaria": listar_valores_distintos("categoria_primaria"),
            "subcategoria": listar_valores_distintos("subcategoria"),
        },
        args_atuais=request.args.to_dict(flat=False),
    )


@app.route("/receitas")
def receitas():
    """Endereço anterior da tela única de receitas — hoje partida em duas.

    Vira redirecionamento em vez de sumir: link salvo e favorito continuam
    funcionando, mesmo padrão do /contas-pagar."""
    return redirect(url_for("receitas_vendas", **request.args))


def _tela_de_receitas(tabela: str, rota: str, titulo: str):
    """Monta a tela de Vendas ou de Serviços. As duas são a mesma listagem com
    o tipo de nota fixo, então compartilham view e template — o que muda é a
    chave de tabela usada pelos funis (ver app/filtros_coluna.py)."""
    filtros_coluna = _filtros_da_url(COLUNAS_FILTRAVEIS[tabela])

    ordenar = request.args.get("ordenar") or "data_emissao"
    if ordenar not in COLUNAS_ORDENAVEIS_NOTAS:
        ordenar = "data_emissao"
    direcao = "asc" if request.args.get("direcao") == "asc" else "desc"

    notas = consulta.LISTAGEM[tabela](filtros_coluna, ordenar=ordenar, direcao=direcao)
    faturadas = [n for n in notas if n["considerar_efetivo"]]

    return render_template(
        "receitas.html",
        tabela=tabela,
        rota=rota,
        titulo=titulo,
        secao=tabela,
        notas=notas,
        total_receita=sum(n["valor"] or 0 for n in faturadas),
        total_excluido=sum(n["valor"] or 0 for n in notas if not n["considerar_efetivo"]),
        quantidade=len(faturadas),
        excluidas=len(notas) - len(faturadas),
        filtros_coluna=filtros_coluna,
        categorias_sugeridas=categorias_conhecidas(),
        ordenar=ordenar,
        direcao=direcao,
        args_atuais=request.args.to_dict(flat=False),
    )


@app.route("/receitas/vendas")
def receitas_vendas():
    return _tela_de_receitas("receitas_vendas", "receitas_vendas", "Receitas Vendas")


@app.route("/receitas/servicos")
def receitas_servicos():
    return _tela_de_receitas("receitas_servicos", "receitas_servicos", "Receitas Serviços")


@app.route("/analise-receitas")
def analise_receitas():
    """Análise de faturamento com a categoria como espinha dorsal.

    Ao contrário de /dashboard, aqui não entra despesa nem rateio: a pergunta é
    de onde vem o dinheiro e em que mês ele parou de vir."""
    def multi(nome):
        return [v for v in request.args.getlist(nome) if v]

    competencias_marcadas = multi("competencia")
    tipos_marcados = multi("tipo_nota")
    categorias_marcadas = multi("categoria_primaria_efetiva")

    filtros = {
        "competencia": competencias_marcadas,
        "tipo_nota": tipos_marcados,
        "categoria_primaria_efetiva": categorias_marcadas,
    }

    notas = listar_notas(
        {"tipo_nota": tipos_marcados} if tipos_marcados else {},
        competencias=set(competencias_marcadas) or None,
        categorias=set(categorias_marcadas) or None,
    )
    faturadas = [n for n in notas if n["considerar_efetivo"]]

    # As opções dos slicers saem do universo INTEIRO, não do recorte filtrado:
    # os slicers do dashboard não cascateiam (decisão de 24/08/2026), e sem isso
    # marcar uma categoria apagaria as outras da lista.
    todas = [n for n in listar_notas({}) if n["considerar_efetivo"]]

    return render_template(
        "analise_receitas.html",
        secao="analise_receitas",
        grade=grades(faturadas),
        filtros=filtros,
        opcoes={
            "competencia": sorted(
                {n["competencia_efetiva"] for n in todas if n["competencia_efetiva"]},
                key=lambda c: (c[3:], c[:2]),
            ),
            "tipo_nota": sorted({n["tipo_nota"] for n in todas if n["tipo_nota"]}),
            "categoria_primaria_efetiva": sorted(
                {(n["categoria_primaria_efetiva"] or "").strip() for n in todas
                 if (n["categoria_primaria_efetiva"] or "").strip()}
            ),
        },
    )


@app.route("/receitas/ajustar", methods=["POST"])
def receitas_ajustar():
    """Grava a edição manual de competência/categoria de uma nota.

    O valor original do ERP não é tocado — o ajuste vai para coluna própria."""
    d = request.get_json()
    definir_ajuste(
        d["empresa"], d["tipo_nota"], d["id"],
        competencia=d.get("competencia"),
        categoria=d.get("categoria"),
    )
    return jsonify({"ok": True})


@app.route("/despesas/marcar", methods=["POST"])
def marcar_conta():
    dados = request.get_json()
    empresa = dados["empresa"]
    id_conta = dados["id"]
    considerar = dados["considerar"]  # true, false, ou null (volta pro padrão)
    definir_manual(empresa, id_conta, considerar)
    return jsonify({"ok": True})


@app.route("/receitas/marcar", methods=["POST"])
def marcar_nota():
    """Override "considerar/desconsiderar" de uma nota. O dado do ERP não muda."""
    dados = request.get_json()
    definir_marcacao(
        dados["empresa"],
        dados["tipo_nota"],
        dados["id"],
        dados["considerar"],  # true, false, ou null (volta pro padrão da situação)
    )
    return jsonify({"ok": True})


@app.route("/extracao")
def extracao():
    hoje = date.today()
    return render_template(
        "extracao.html",
        empresas=load_companies(),
        anos=list(range(hoje.year - 3, hoje.year + 2)),
        ano_atual=hoje.year,
    )


@app.route("/extracao/iniciar", methods=["POST"])
def extracao_iniciar():
    dados = request.get_json()
    ok, mensagem = iniciar(
        dados.get("empresa"),
        int(dados.get("ano")),
        forcar=bool(dados.get("forcar")),
    )
    return jsonify({"ok": ok, "mensagem": mensagem}), (200 if ok else 409)


@app.route("/extracao/status")
def extracao_status():
    return jsonify(estado_atual())


@app.route("/configuracoes/exclusoes", methods=["GET", "POST"])
def configuracoes_exclusoes():
    if request.method == "POST":
        categorias_marcadas = request.form.getlist("categoria_primaria")
        subcategorias_marcadas = request.form.getlist("subcategoria")
        definir_regras_exclusao("categoria_primaria", categorias_marcadas)
        definir_regras_exclusao("subcategoria", subcategorias_marcadas)
        return redirect(url_for("configuracoes_exclusoes"))

    regras = listar_regras_exclusao()
    return render_template(
        "configuracoes_exclusoes.html",
        categorias_primarias=listar_valores_distintos("categoria_primaria"),
        subcategorias=listar_valores_distintos("subcategoria"),
        categorias_excluidas=set(regras.get("categoria_primaria", [])),
        subcategorias_excluidas=set(regras.get("subcategoria", [])),
    )


if __name__ == "__main__":
    # use_reloader desligado de propósito: o projeto fica dentro do OneDrive, e a
    # sincronização dele "toca" nos arquivos, fazendo o Flask reiniciar sozinho e
    # matar a extração em andamento (já aconteceu, perdendo 15 min de chamadas).
    # Se mexer no código, pare e rode de novo.
    app.run(debug=True, use_reloader=False)
