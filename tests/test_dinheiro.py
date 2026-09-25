"""Dinheiro em centavos e Decimal (Fase 1, etapa C).

A regra: centavos no banco, Decimal no cálculo, meio centavo sobe, e toda
partilha soma EXATAMENTE o total partilhado (resíduo na maior parte).
"""

import sqlite3
from decimal import Decimal as D

import pytest

from financeiro import db, migracao_centavos
from financeiro.dinheiro import arredondar, como_decimal, para_centavos, para_reais, ratear
from financeiro.centros_de_custo import separar
from tests.conftest import _conta, _nota, gravar

# ---- conversões -------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, centavos",
    [
        ("1234.56", 123456),
        (1234.56, 123456),
        (0.1 + 0.2, 30),  # float com ruído: vale o texto arredondado
        (D("10.005"), 1001),  # meio centavo sobe
        (D("-10.005"), -1001),  # e desce no negativo (afasta do zero)
        (7, 700),
        (None, None),
        ("", None),
        ("abc", None),
        (float("nan"), None),
    ],
)
def test_para_centavos(entrada, centavos):
    assert para_centavos(entrada) == centavos


def test_ida_e_volta_nao_perde_centavo():
    for c in (0, 1, 99, 100, 123456789, -5):
        assert para_centavos(para_reais(c)) == c
    assert para_reais(None) is None
    assert para_reais(123456) == D("1234.56")


def test_arredondamento_comercial():
    assert arredondar(D("0.125")) == D("0.13")
    assert arredondar(D("0.124999")) == D("0.12")
    assert como_decimal(None) == 0 and como_decimal(1.1) == D("1.1")


# ---- rateio -------------------------------------------------------------------


@pytest.mark.parametrize(
    "total, pesos",
    [
        (D("100.00"), [D(1), D(1), D(1)]),  # 33,33 × 3 = 99,99: sobra 1 centavo
        (D("0.01"), [D(1), D(1)]),
        (D("1741081.65"), [D("12.3"), D("45.6"), D("0.01"), D("999")]),
        (D("-50.00"), [D(3), D(7)]),
    ],
)
def test_partes_somam_exatamente_o_total(total, pesos):
    partes = ratear(total, pesos)
    assert sum(partes) == total
    assert all(p == arredondar(p) for p in partes)  # todas em centavos


def test_residuo_vai_para_a_maior_parte():
    # 100 / 3 = 33,333...: cada parte arredonda para 33,33 e sobra 0,01.
    assert ratear(D("100.00"), [D(1), D(5), D(1)]) == [D("14.29"), D("71.42"), D("14.29")]
    assert ratear(D("100.00"), [D(1), D(1), D(1)]) == [D("33.34"), D("33.33"), D("33.33")]


def test_sem_base_nada_e_distribuido():
    assert ratear(D("10.00"), [D(0), D(0)]) == [D(0), D(0)]
    assert ratear(D("10.00"), []) == []


def test_separar_reparte_o_adm_geral_sem_criar_nem_perder_centavo():
    """ADM GERAL com meio centavo nos 10%: Vendas arredonda para cima e
    Serviços fica com o complemento exato — as duas cotas somam o bolo."""
    notas = [_n("COMERCIO", "100"), _n("OBRA X", "300"), _n("OBRA Y", "300")]
    contas = [{"categoria_primaria": "ADM GERAL", "valor": D("9490.45")}]
    b = separar(notas, contas)
    cotas = b["rateio"]["por_bloco"]
    assert cotas["Vendas"]["adm1"] == D("949.05")  # 949,045 -> 949,05
    assert cotas["Serviços"]["adm1"] == D("8541.40")  # o complemento
    assert b["total"]["adm1"] == D("9490.45")
    servicos = {l["nome"]: l["adm1"] for l in b["servicos"]["linhas"]}
    assert sum(servicos.values()) == D("8541.40")  # 4270,70 + 4270,70


def _n(categoria, valor):
    return {"categoria_primaria_efetiva": categoria, "valor": D(valor)}


# ---- migração 3 ---------------------------------------------------------------


def _banco_v2(caminho):
    """Banco na versão 2 (REAL), com valores que o float representa mal."""
    conn = sqlite3.connect(caminho)
    conn.execute("CREATE TABLE schema_versao (versao INTEGER PRIMARY KEY, aplicado_em TEXT)")
    for arquivo in ("0001_esquema_inicial.sql", "0002_integridade_auditoria.sql"):
        conn.executescript((db.PASTA_MIGRACOES / arquivo).read_text("utf-8"))
    conn.executemany("INSERT INTO schema_versao VALUES (?, 'x')", [(1,), (2,)])
    conn.commit()
    conn.close()
    gravar(
        caminho,
        [
            _conta("ALFA", 1, "A-B", 0.1 + 0.2, "01/2026"),
            _conta("ALFA", 2, "A-B", 1234567.89, "01/2026"),
        ],
        [_nota("ALFA", "venda", 9, "C-D", 79.99, "01/2026")],
    )


def test_migracao_3_converte_exato(tmp_path):
    caminho = tmp_path / "v2.db"
    _banco_v2(caminho)
    db.migrar(caminho, tmp_path / "bkp")
    conn = sqlite3.connect(caminho)
    assert conn.execute("SELECT valor_centavos FROM contas_pagar ORDER BY id").fetchall() == [
        (30,),
        (123456789,),
    ]
    assert conn.execute("SELECT valor_centavos, typeof(valor_centavos) FROM notas").fetchone() == (
        7999,
        "integer",
    )
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(contas_pagar)")}
    assert (
        "valor" not in colunas and {"valor_centavos", "saldo_centavos", "pago_centavos"} <= colunas
    )
    with pytest.raises(sqlite3.IntegrityError):  # float não entra mais
        conn.execute("UPDATE contas_pagar SET valor_centavos = 1.5")
    conn.close()


def test_migracao_3_desfaz_tudo_se_a_reconciliacao_falhar(tmp_path, monkeypatch):
    """Simula um erro de conversão: a reconciliação acusa e a migração inteira
    volta atrás — tabela ainda em REAL, versão 2."""
    caminho = tmp_path / "v2.db"
    _banco_v2(caminho)
    original = migracao_centavos._recriar

    def recriar_com_defeito(conn, tabela):
        original(conn, tabela)
        conn.execute(f"UPDATE {tabela} SET valor_centavos = valor_centavos + 1 WHERE rowid = 1")

    monkeypatch.setattr(migracao_centavos, "_recriar", recriar_com_defeito)
    with pytest.raises(migracao_centavos.ReconciliacaoFalhou):
        db.migrar(caminho, tmp_path / "bkp")

    conn = sqlite3.connect(caminho)
    assert conn.execute("SELECT max(versao) FROM schema_versao").fetchone()[0] == 2
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(contas_pagar)")}
    assert "valor" in colunas and "valor_centavos" not in colunas
    assert conn.execute("SELECT count(*) FROM contas_pagar").fetchone()[0] == 2
    conn.close()
    assert list((tmp_path / "bkp").glob("*.db"))  # e o backup ficou


def test_migracao_3_recusa_valor_com_mais_de_duas_casas(tmp_path):
    caminho = tmp_path / "v2.db"
    _banco_v2(caminho)
    conn = sqlite3.connect(caminho)
    conn.execute("UPDATE contas_pagar SET valor = 10.005 WHERE id = '1'")
    conn.commit()
    conn.close()
    with pytest.raises(migracao_centavos.ReconciliacaoFalhou, match="mais de 2 casas"):
        db.migrar(caminho, tmp_path / "bkp")


def test_tela_mostra_reais_a_partir_dos_centavos(cliente):
    """A linha lida do banco traz `valor` em reais Decimal."""
    from tests.test_telas import _contexto

    c = _contexto(cliente, "/despesas")
    assert all(isinstance(l["valor"], D) for l in c["contas"])
    assert isinstance(c["total_considerado"], D)
