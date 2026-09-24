"""_considerar_efetivo, nos dois lados (despesas e receitas).

A coluna "Considerar" é derivada: o override manual manda; sem ele valem as
regras de exclusão (despesa) ou a situação da nota (receita). Um erro aqui muda
o fechamento inteiro sem mudar nenhum dado do banco.
"""

import pytest

from app import receitas
from app.repositorio_contas_pagar import _considerar_efetivo as considerar_conta

REGRAS = {"categoria_primaria": ["APORTE", "IMPOSTO"], "subcategoria": ["APORTE"]}


def _conta(primaria, sub=None, manual=None):
    return {"categoria_primaria": primaria, "subcategoria": sub, "considerar_manual": manual}


# ---- despesas -------------------------------------------------------------


def test_conta_comum_entra():
    assert considerar_conta(_conta("COMERCIO", "Frete"), REGRAS) is True


def test_regra_por_categoria_primaria_exclui():
    assert considerar_conta(_conta("IMPOSTO", "ISS"), REGRAS) is False


def test_regra_por_subcategoria_exclui_mesmo_com_primaria_livre():
    # A subcategoria sozinha basta: primária OU subcategoria na regra.
    assert considerar_conta(_conta("OBRA X", "APORTE"), REGRAS) is False


@pytest.mark.parametrize("manual, esperado", [(1, True), (0, False)])
def test_override_manual_vence_a_regra(manual, esperado):
    # Marcada à mão vale mais que a regra, nos dois sentidos.
    assert considerar_conta(_conta("IMPOSTO", "ISS", manual), REGRAS) is esperado
    assert considerar_conta(_conta("COMERCIO", "Frete", manual), REGRAS) is esperado


def test_regra_compara_texto_exato():
    # Comportamento ATUAL, registrado de propósito: a regra casa pelo texto
    # exato, sem ignorar caixa nem espaço. "Imposto" (minúsculas) ou "IMPOSTO "
    # passariam como consideradas. Se isso mudar, o golden master aponta onde.
    assert considerar_conta(_conta("Imposto"), REGRAS) is True
    assert considerar_conta(_conta("IMPOSTO "), REGRAS) is True


def test_sem_categoria_entra():
    assert considerar_conta(_conta(None), REGRAS) is True


# ---- receitas -------------------------------------------------------------


@pytest.mark.parametrize(
    "situacao, esperado",
    [
        ("Emitida DANFE", True),
        ("Autorizada", True),
        ("Emitida", True),
        ("Cancelada", False),
        ("Rejeitada", False),
        ("Denegada", False),
        ("Pendente", False),
        # Comparação por trecho em maiúsculas: variação de caixa não escapa.
        ("cancelada pelo emitente", False),
        # Sem situação é tratada como receita (nada no texto a excluir).
        (None, True),
    ],
)
def test_nota_segue_a_situacao(situacao, esperado):
    nota = {"descricao_situacao": situacao, "considerar_manual": None}
    assert receitas._considerar_efetivo(nota) is esperado


def test_excluida_com_acento_nao_e_reconhecida():
    # Comportamento ATUAL: a lista tem "EXCLUIDA" sem acento. Se o Tiny mandar
    # "Excluída", "EXCLUÍDA" não contém "EXCLUIDA" e a nota ENTRA como receita.
    # Registrado aqui para o relatório de qualidade — não corrigido nesta fase.
    nota = {"descricao_situacao": "Excluída", "considerar_manual": None}
    assert receitas._considerar_efetivo(nota) is True


@pytest.mark.parametrize("manual, esperado", [(1, True), (0, False)])
def test_override_manual_vence_a_situacao(manual, esperado):
    cancelada = {"descricao_situacao": "Cancelada", "considerar_manual": manual}
    emitida = {"descricao_situacao": "Autorizada", "considerar_manual": manual}
    assert receitas._considerar_efetivo(cancelada) is esperado
    assert receitas._considerar_efetivo(emitida) is esperado
