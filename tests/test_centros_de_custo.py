"""separar(): resultado por categoria com imposto, Adm I e Adm II rateados.

Os valores são sintéticos e redondos para a conta caber de cabeça. Cenário base:

  Vendas    COMERCIO  receita 10.000  despesa 1.000
  Serviços  OBRA X    receita 20.000  despesa 3.000
            OBRA SEM  receita      0  despesa   400   (custo puro)
  Sem classificação   despesa 60
  Fontes de rateio: ADM GERAL 2.000 · ADM MSV 500 · ADM START GTF 900
"""

import pytest

from app.centros_de_custo import SERVICOS, VENDAS, separar


def _nota(categoria, valor):
    return {"categoria_primaria_efetiva": categoria, "valor": valor}


def _conta(categoria, valor):
    return {"categoria_primaria": categoria, "valor": valor}


NOTAS = [_nota("COMERCIO", 10000.0), _nota("OBRA X", 20000.0)]
CONTAS = [
    _conta("COMERCIO", 1000.0),
    _conta("ADM MSV", 500.0),
    _conta("ADM GERAL", 2000.0),
    _conta("OBRA X", 3000.0),
    _conta("ADM START GTF", 900.0),
    _conta("OBRA SEM RECEITA", 400.0),
    _conta(None, 60.0),
]


@pytest.fixture
def blocos():
    return separar(NOTAS, CONTAS)


def _linha(blocos, bloco, nome):
    return next(l for l in blocos[bloco]["linhas"] if l["nome"] == nome)


def test_vendas_leva_14_por_cento_e_10_por_cento_do_adm_geral(blocos):
    l = _linha(blocos, "vendas", "COMERCIO")
    assert l["imposto"] == pytest.approx(1400.0)  # 14% de 10.000
    assert l["adm1"] == pytest.approx(200.0)  # 10% de 2.000, única com receita
    assert l["adm2"] == pytest.approx(500.0)  # ADM MSV inteiro
    assert l["custo_total"] == pytest.approx(3100.0)
    assert l["resultado"] == pytest.approx(6900.0)
    assert l["margem"] == pytest.approx(69.0)


def test_servicos_leva_10_por_cento_e_90_por_cento_do_adm_geral(blocos):
    l = _linha(blocos, "servicos", "OBRA X")
    assert l["imposto"] == pytest.approx(2000.0)  # 10% de 20.000
    assert l["adm1"] == pytest.approx(1800.0)  # 90% de 2.000
    assert l["adm2"] == pytest.approx(900.0)  # ADM START GTF inteiro
    assert l["resultado"] == pytest.approx(20000 - 3000 - 2000 - 1800 - 900)


def test_categoria_sem_receita_e_custo_puro(blocos):
    l = _linha(blocos, "servicos", "OBRA SEM RECEITA")
    assert (l["imposto"], l["adm1"], l["adm2"]) == (0.0, 0.0, 0.0)
    assert l["resultado"] == pytest.approx(-400.0)
    assert l["margem"] is None  # sem receita não existe margem


def test_categorias_de_adm_viram_coluna_e_nao_linha(blocos):
    nomes = {
        l["nome"] for b in ("vendas", "servicos", "sem_classificacao") for l in blocos[b]["linhas"]
    }
    assert not nomes & {"ADM GERAL", "ADM MSV", "ADM START GTF"}


def test_sem_classificacao_nao_leva_imposto_nem_rateio(blocos):
    l = blocos["sem_classificacao"]["linhas"][0]
    assert l["nome"] == "(sem categoria)"
    assert (l["imposto"], l["adm1"], l["adm2"]) == (None, None, None)
    assert l["custo_total"] == pytest.approx(60.0)
    # E aparece no resumo, porque existe.
    assert [r["nome"] for r in blocos["resumo"]] == [VENDAS, SERVICOS, "Sem classificação"]


def test_total_fecha_com_o_dinheiro_que_entrou(blocos):
    # Nenhum real some nem aparece duas vezes: o custo total é toda a despesa
    # (inclusive as de Adm, agora como coluna) mais o imposto calculado.
    t = blocos["total"]
    despesa_bruta = sum(c["valor"] for c in CONTAS)
    assert t["receita"] == pytest.approx(30000.0)
    assert t["imposto"] == pytest.approx(3400.0)
    assert t["custo_total"] == pytest.approx(despesa_bruta + 3400.0)
    assert t["resultado"] == pytest.approx(30000.0 - despesa_bruta - 3400.0)


def test_rateio_distribui_o_bolo_inteiro_entre_as_categorias_com_receita():
    notas = [_nota("OBRA X", 30000.0), _nota("OBRA Y", 10000.0)]
    contas = [_conta("ADM GERAL", 1000.0), _conta("ADM START GTF", 400.0)]
    b = separar(notas, contas)
    x, y = _linha(b, "servicos", "OBRA X"), _linha(b, "servicos", "OBRA Y")
    # 75% / 25% pela receita.
    assert x["adm1"] == pytest.approx(900.0 * 0.75)
    assert y["adm1"] == pytest.approx(900.0 * 0.25)
    assert x["adm2"] + y["adm2"] == pytest.approx(400.0)


def test_adm_geral_inativo_conta_como_adm_geral():
    b = separar([_nota("COMERCIO", 100.0)], [_conta("ADM GERAL INATIVO", 1000.0)])
    assert b["rateio"]["adm_geral"] == pytest.approx(1000.0)
    assert _linha(b, "vendas", "COMERCIO")["adm1"] == pytest.approx(100.0)


def test_classificacao_ignora_caixa_e_espaco():
    b = separar([_nota(" comercio ", 100.0)], [])
    assert b["vendas"]["linhas"][0]["receita"] == pytest.approx(100.0)


def test_bloco_sem_receita_perde_o_adm_do_bloco():
    """Comportamento ATUAL, registrado para o relatório da Fase 0.

    Se um bloco não tem receita no recorte (ex.: filtro só de uma empresa de
    serviços), o peso de todas as linhas dele é zero e a cota de Adm I e Adm II
    daquele bloco não vai para lugar nenhum: some do custo total e o Resultado
    do Total fica MAIOR do que a despesa real permite.

    Aqui: 500 de ADM MSV e 10% de 1.000 do ADM GERAL (=100) somem, porque não
    há receita de Vendas. Se a regra mudar, este teste muda junto — com
    decisão registrada no HISTORICO.md."""
    notas = [_nota("OBRA X", 10000.0)]
    contas = [_conta("ADM MSV", 500.0), _conta("ADM GERAL", 1000.0)]
    b = separar(notas, contas)
    assert b["rateio"]["por_bloco"][VENDAS]["adm2"] == pytest.approx(500.0)
    assert b["vendas"]["totais"]["adm2"] == 0.0
    # Do bolo de 1.500 de Adm, só os 900 de Serviços chegam ao total.
    assert b["total"]["adm1"] + b["total"]["adm2"] == pytest.approx(900.0)
    assert b["total"]["custo_total"] == pytest.approx(10000 * 0.10 + 900.0)


def test_sem_nada_nao_quebra():
    b = separar([], [])
    assert b["total"]["resultado"] == 0.0
    assert b["total"]["margem"] is None
    assert len(b["resumo"]) == 2  # Sem classificação só entra se existir
