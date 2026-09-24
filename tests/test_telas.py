"""As telas sobre o banco sintético: o número que aparece é o número certo.

Captura o contexto que a rota manda ao template (sinal `template_rendered` do
Flask) em vez de raspar o HTML: o teste enxerga o número que a tela recebe,
sem depender de layout — que muda na Fase 3.
"""

from contextlib import contextmanager

import pytest
from flask import template_rendered


@contextmanager
def capturar(app):
    registros = []

    def receptor(sender, template, context, **extra):
        registros.append(context)

    template_rendered.connect(receptor, app)
    try:
        yield registros
    finally:
        template_rendered.disconnect(receptor, app)


def _contexto(cliente, url):
    with capturar(cliente.application) as ctx:
        r = cliente.get(url)
    assert r.status_code == 200
    return ctx[0]


def test_despesas_soma_so_as_consideradas_e_so_de_2026(cliente):
    c = _contexto(cliente, "/despesas")
    # 11 contas visíveis (a de 12/2025 fica fora da visão).
    assert len(c["contas"]) == 11
    # Consideradas: tudo menos IMPOSTO-ISS (regra), APORTE (regra) e a
    # desmarcada à mão; a IMPOSTO-PIS marcada à mão entra.
    assert c["total_considerado"] == pytest.approx(1000 + 500 + 2000 + 3000 + 900 + 100 + 400 + 60)


def test_receitas_servico_mostra_nota_sem_competencia(cliente):
    c = _contexto(cliente, "/receitas/servicos")
    assert {n["id"] for n in c["notas"]} == {"201", "202", "203", "204"}
    assert c["quantidade"] == 3  # a cancelada não conta
    assert c["total_receita"] == pytest.approx(20000 + 1000 + 700)
    assert c["total_excluido"] == pytest.approx(5000)


def test_dashboard_de_janeiro_fecha_com_o_calculo_manual(cliente):
    c = _contexto(cliente, "/dashboard?competencia=01/2026")
    assert c["total_receita"] == pytest.approx(30000)
    assert c["total_despesa"] == pytest.approx(1000 + 500 + 2000 + 3000 + 900 + 400 + 60)
    t = c["blocos"]["total"]
    # Imposto 14% de 10.000 + 10% de 20.000; Adm inteiro rateado (os dois
    # blocos têm receita em janeiro, então nada se perde).
    assert t["imposto"] == pytest.approx(3400)
    assert t["adm1"] + t["adm2"] == pytest.approx(2000 + 500 + 900)
    assert t["resultado"] == pytest.approx(30000 - 7860 - 3400)


def test_dashboard_usa_a_competencia_manual_da_nota(cliente):
    c = _contexto(cliente, "/dashboard?competencia=02/2026")
    # A nota 203 não tem competência no ERP; o ajuste manual a põe em 02/2026.
    assert c["total_receita"] == pytest.approx(1000)
    assert c["quantidade_notas"] == 1


def test_dashboard_sem_slicer_usa_o_periodo_padrao(cliente):
    """Correção da Fase 1 (item 3): sem competência marcada, o Dashboard mostra
    de 01/2026 ao último mês com receita (aqui 02/2026, pela nota 203 ajustada
    à mão) — não "tudo". Fica fora a nota sem competência (700) e a conta de
    competência futura não entraria no Total."""
    c = _contexto(cliente, "/dashboard")
    assert c["periodo_padrao"]["inicio"] == "01/2026"
    assert c["periodo_padrao"]["fim"] == "02/2026"
    assert c["total_receita"] == pytest.approx(20000 + 10000 + 1000)
    corpo = cliente.get("/dashboard").get_data(as_text=True)
    assert "01/2026 a 02/2026" in corpo


def test_dashboard_com_slicer_nao_usa_periodo_padrao(cliente):
    c = _contexto(cliente, "/dashboard?competencia=01/2026")
    assert c["periodo_padrao"] is None


def test_conta_sem_competencia_aparece_como_vazio(cliente, banco_exemplo):
    """Correção da Fase 1 (item 2): conta com competência vazia não some mais —
    aparece em Despesas e no funil como "(vazio)", mas não vira opção de mês
    no slicer do Dashboard."""
    from tests.conftest import _conta, gravar

    gravar(banco_exemplo, [_conta("ALFA", 90, "COMERCIO-Frete", 55.0, "")])
    c = _contexto(cliente, "/despesas")
    assert "90" in {x["id"] for x in c["contas"]}
    arvore = cliente.get("/api/valores-filtro?tabela=despesas&coluna=competencia").get_json()
    assert arvore["arvore"][-1]["valor"] == "(vazio)"
    assert "" not in _contexto(cliente, "/dashboard")["opcoes"]["competencia"]
