"""Painel de pendências e selo de sincronização (Fase 4.1), com dados sintéticos.

O banco de exemplo (conftest) já traz: conta sem categoria (BETA, 60) e nota
de serviço sem competência (BETA, 700). Cada teste acrescenta o caso que mede.
"""

import sqlite3
from datetime import date

import pytest
from flask import url_for

from financeiro import pendencias
from financeiro.escopo import SISTEMA, Escopo
from tests.conftest import _conta, _nota, cliente_para, gravar


def _por_chave(escopo):
    return {p.chave: p for p in pendencias.calcular(escopo, hoje=date(2026, 9, 24))}


def test_conta_da_contagem_e_valor_por_empresa(banco_exemplo):
    gravar(
        banco_exemplo,
        [
            _conta("ALFA", 50, "COMERCIO-Frete", 10.0, ""),  # sem competência
            _conta("ALFA", 51, "COMERCIO-Frete", 20.0, "07/2800"),  # absurda
            _conta("GAMA", 52, "X-Y", 5.0, "13/2026"),  # mês inválido
        ],
        [_nota("ALFA", "venda", 150, None, 300.0, "01/2026")],  # venda sem categoria
    )
    p = _por_chave(SISTEMA)
    assert dict(p["contas_sem_competencia"].por_empresa) == {"ALFA": [1, pytest.approx(10)]}
    assert p["contas_competencia_absurda"].quantidade == 2
    assert p["contas_competencia_absurda"].filtros == {"competencia": ["07/2800", "13/2026"]}
    assert dict(p["contas_sem_categoria"].por_empresa)["BETA"][0] == 1
    assert p["notas_sem_competencia"].quantidade == 1  # a 204 da BETA
    assert p["notas_sem_categoria"].quantidade == 1  # a 150 da ALFA


def test_nota_desconsiderada_nao_e_pendencia(banco_exemplo):
    gravar(
        banco_exemplo,
        notas=[_nota("ALFA", "venda", 151, None, 1.0, "01/2026", considerar_manual=0)],
    )
    assert _por_chave(SISTEMA)["notas_sem_categoria"].quantidade == 0


def test_grafia_divergente_conta_um_grupo_por_fornecedor(banco_exemplo):
    gravar(
        banco_exemplo,
        [
            _conta("ALFA", 60, "A-B", 1.0, "01/2026", fornecedor="Fulano"),
            _conta("ALFA", 61, "A-B", 1.0, "01/2026", fornecedor="FULANO"),
            _conta("ALFA", 62, "A-B", 1.0, "01/2026", fornecedor="fulano "),
        ],
    )
    g = _por_chave(SISTEMA)["fornecedores_grafia"]
    assert g.quantidade == 1
    ((rotulo, filtros),) = g.exemplos
    assert filtros["empresa"] == "ALFA" and len(filtros["fornecedor"]) == 3


def test_escopo_limita_as_pendencias(banco_exemplo):
    alfa = Escopo(usuario_id=9, login="x", perfil="leitura", empresas=frozenset({"ALFA"}))
    p = _por_chave(alfa)
    assert p["contas_sem_categoria"].quantidade == 0  # a sem categoria é da BETA
    assert p["notas_sem_competencia"].quantidade == 0


@pytest.mark.parametrize(
    "chave, contagem_na_tela",
    [
        ("contas_sem_categoria", lambda c: len(c["contas"])),
        ("notas_sem_competencia", lambda c: len(c["notas"])),
    ],
)
def test_link_leva_exatamente_as_linhas_contadas(banco_exemplo, chave, contagem_na_tela):
    from tests.test_telas import _contexto

    cliente = cliente_para(banco_exemplo)
    p = _por_chave(SISTEMA)[chave]
    with cliente.application.test_request_context():
        url = url_for(p.rota, **p.parametros("BETA"))
    assert contagem_na_tela(_contexto(cliente, url)) == p.por_empresa["BETA"][0]


def test_painel_abre_para_leitura(banco_exemplo):
    c = cliente_para(banco_exemplo, perfil="leitura", empresas=("BETA",))
    corpo = c.get("/pendencias").get_data(as_text=True)
    assert "Notas de serviço sem competência" in corpo
    assert "Onde corrigir" in corpo


# ---- selo ----------------------------------------------------------------------------


def _sincronizou(caminho, empresa, tipo, quando, status="ok"):
    conn = sqlite3.connect(caminho)
    conn.execute(
        "INSERT INTO sincronizacoes (lote, origem, empresa, tipo, iniciada_em, terminada_em, status)"
        " VALUES ('l', 'cli', ?, ?, ?, ?, ?)",
        (empresa, tipo, quando, quando, status),
    )
    conn.commit()
    conn.close()


def _tudo_em(caminho, quando):
    for empresa in ("ALFA", "BETA"):
        for tipo in ("contas", "notas"):
            _sincronizou(caminho, empresa, tipo, quando)


def test_selo_verde_quando_em_dia(banco_exemplo):
    _tudo_em(banco_exemplo, "2026-09-23T06:00:00")
    s = pendencias.selo(SISTEMA, hoje=date(2026, 9, 24))
    assert (s.dias, s.alerta, s.texto) == (1, False, "sincronizado há 1 dia")


def test_selo_vermelho_acima_de_dois_dias(banco_exemplo):
    _tudo_em(banco_exemplo, "2026-09-24T06:00:00")
    _sincronizou(banco_exemplo, "BETA", "notas", "2026-09-20T06:00:00", status="erro")
    # A última de SUCESSO das notas da BETA continua hoje: verde.
    assert pendencias.selo(SISTEMA, hoje=date(2026, 9, 24)).alerta is False
    # Mas se o último sucesso de um só par é de 3 dias atrás, o selo inteiro fica vermelho.
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("DELETE FROM sincronizacoes WHERE empresa='BETA' AND tipo='notas'")
    conn.commit()
    conn.close()
    _sincronizou(banco_exemplo, "BETA", "notas", "2026-09-21T06:00:00")
    s = pendencias.selo(SISTEMA, hoje=date(2026, 9, 24))
    assert (s.dias, s.alerta) == (3, True)
    assert "BETA receitas: 2026-09-21 06:00" in s.dica


def test_selo_sem_historico_usa_a_gravacao_das_linhas(banco_exemplo):
    # O conftest grava as linhas com atualizado_em de 01/01/2026.
    s = pendencias.selo(SISTEMA, hoje=date(2026, 9, 24))
    assert s.alerta is True and s.dias == (date(2026, 9, 24) - date(2025, 12, 31)).days


def test_selo_do_escopo_ignora_empresa_que_o_usuario_nao_ve(banco_exemplo):
    _tudo_em(banco_exemplo, "2026-09-24T06:00:00")
    _sincronizou(banco_exemplo, "BETA", "contas", "2026-09-24T07:00:00")
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("DELETE FROM sincronizacoes WHERE empresa='BETA'")
    conn.commit()
    conn.close()
    alfa = Escopo(usuario_id=9, login="x", perfil="leitura", empresas=frozenset({"ALFA"}))
    assert pendencias.selo(alfa, hoje=date(2026, 9, 24)).alerta is False
    assert pendencias.selo(SISTEMA, hoje=date(2026, 9, 24)).alerta is True  # BETA sem sucesso


def test_selo_aparece_no_topo_de_toda_tela(banco_exemplo):
    c = cliente_para(banco_exemplo)
    for rota in ("/despesas", "/dashboard", "/pendencias"):
        assert "selo-sincronizacao" in c.get(rota).get_data(as_text=True)
    assert "selo-sincronizacao" not in cliente_para(banco_exemplo, logado=False).get(
        "/login"
    ).get_data(as_text=True)
