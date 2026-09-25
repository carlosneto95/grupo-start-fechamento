"""Recorte de visão (visao.py): casa_data, competência visível e formato do valor.

casa_data é o que permite o filtro em árvore mandar a seleção colapsada
("2026" em vez de 365 dias). Se ele falhar, marcar um ano no funil esvazia a
tabela ou, pior, deixa passar linha que não devia.
"""

import pytest

from financeiro.visao import SEM_VALOR, casa_data, competencia_visivel, formatar_valor


@pytest.mark.parametrize(
    "bruto, selecionadas, esperado",
    [
        # Data completa casa por qualquer nível: dia, mês ou ano.
        ("05/08/2026", {"05/08/2026"}, True),
        ("05/08/2026", {"08/2026"}, True),
        ("05/08/2026", {"2026"}, True),
        ("05/08/2026", {"06/08/2026", "07/2026", "2025"}, False),
        # Competência (mm/aaaa) casa por mês ou por ano.
        ("08/2026", {"08/2026"}, True),
        ("08/2026", {"2026"}, True),
        ("08/2026", {"09/2026"}, False),
        # O mês não pode casar com o dia: "08/2026" não é o dia "08" de nada.
        ("08/2026", {"08"}, False),
        # Espaço em volta vindo do ERP não impede o casamento.
        ("  08/2026 ", {"08/2026"}, True),
    ],
)
def test_casa_por_qualquer_nivel(bruto, selecionadas, esperado):
    assert casa_data(bruto, selecionadas) is esperado


@pytest.mark.parametrize("bruto", [None, "", "   "])
def test_celula_vazia_so_casa_com_vazio(bruto):
    # Célula em branco só aparece se "(vazio)" estiver marcado — como no Excel.
    assert casa_data(bruto, {SEM_VALOR}) is True
    assert casa_data(bruto, {"2026"}) is False


def test_valor_sujo_do_erp_nao_quebra():
    # Competência absurda (existe uma no ano 2800 no banco real) casa pelo
    # próprio texto e pelo ano, sem exceção: a regra é mostrar a sujeira.
    assert casa_data("07/2800", {"2800"}) is True
    assert casa_data("07/2800", {"2026"}) is False


@pytest.mark.parametrize(
    "competencia, visivel",
    [
        ("01/2026", True),
        ("12/2025", False),
        ("07/2800", True),
        (None, False),
        ("", False),
        ("sem-barra", False),
        ("13/abcd", False),
    ],
)
def test_competencia_visivel(competencia, visivel):
    assert competencia_visivel(competencia) is visivel


@pytest.mark.parametrize(
    "valor, texto",
    [
        (1234.5, "1.234,50"),
        (0, "0,00"),
        (None, "0,00"),
        (-10, "-10,00"),
        (1234567.891, "1.234.567,89"),
        ("abc", "0,00"),
    ],
)
def test_formatar_valor(valor, texto):
    # O filtro da coluna Valor casa por este texto: ele tem de ser idêntico ao da célula.
    assert formatar_valor(valor) == texto
