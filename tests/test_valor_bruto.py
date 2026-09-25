"""valor_bruto_de_servico: a receita da NFS-e é o BRUTO, mesmo com ISS retido.

A API do Tiny devolve `total_nota` já LÍQUIDO quando `descontar_iss_total == "S"`.
Se esta função errar, a receita de serviço inteira cai o valor do ISS retido —
e o imposto calculado (10% da receita) cai junto, em silêncio.
Valores sintéticos: 10.000,00 de bruto com 3% de ISS.
"""

from financeiro.receitas import valor_bruto_de_servico


def test_iss_retido_soma_o_iss_de_volta():
    # A API mandou o líquido (9.700) e o ISS (300): o bruto é a soma.
    detalhe = {"total_nota": "9700.00", "valor_iss": "300.00", "descontar_iss_total": "S"}
    assert valor_bruto_de_servico(detalhe) == 10000.00


def test_sem_retencao_total_ja_e_o_bruto():
    # Sem retenção o ISS existe, mas não foi descontado: somar duplicaria.
    detalhe = {"total_nota": "10000.00", "valor_iss": "300.00", "descontar_iss_total": "N"}
    assert valor_bruto_de_servico(detalhe) == 10000.00


def test_flag_ausente_nao_soma():
    # Flag ausente é tratada como "não retido" — o default seguro é não inflar.
    assert valor_bruto_de_servico({"total_nota": "500", "valor_iss": "15"}) == 500.00


def test_flag_com_espacos_ainda_conta():
    # _texto() faz strip: " S " vindo do ERP continua valendo como retido.
    detalhe = {"total_nota": "970", "valor_iss": "30", "descontar_iss_total": " S "}
    assert valor_bruto_de_servico(detalhe) == 1000.00


def test_retido_sem_valor_iss_fica_no_total():
    # Retido mas sem o valor do ISS: não há como reconstruir, fica o total.
    assert valor_bruto_de_servico({"total_nota": "970", "descontar_iss_total": "S"}) == 970.00


def test_sem_total_devolve_none():
    # Sem total_nota não existe valor — None, e não zero, para a nota não
    # parecer uma receita de R$ 0,00 conferida.
    assert valor_bruto_de_servico({"valor_iss": "30", "descontar_iss_total": "S"}) is None
    assert valor_bruto_de_servico({"total_nota": "abc"}) is None


def test_arredonda_no_centavo():
    # Soma de float: 0,1 + 0,2 não pode virar 0,30000000000000004 no banco.
    detalhe = {"total_nota": "0.1", "valor_iss": "0.2", "descontar_iss_total": "S"}
    assert valor_bruto_de_servico(detalhe) == 0.3
