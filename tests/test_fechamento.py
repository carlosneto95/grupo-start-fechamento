"""Fechamento de competência (Fase 4.2), com dados sintéticos.

Banco de exemplo (conftest), competência 01/2026: 8 contas (6 consideradas,
7.860,00) e 3 notas (2 faturadas, 30.000,00). Decisões do Neto: o Dashboard
mostra o número vivo + alerta; os ajustes manuais do mês fechado ficam
travados até um Admin reabrir.
"""

import sqlite3

import pytest

from app import fechamento
from app.escopo import SISTEMA, Escopo
from tests.conftest import _conta, cliente_para, gravar


def _sql(caminho, comando, params=()):
    conn = sqlite3.connect(caminho)
    try:
        conn.execute(comando, params)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def admin(banco_exemplo):
    return cliente_para(banco_exemplo)


def _fechar(cliente, competencia="01/2026"):
    return cliente.post("/fechamento/fechar", data={"competencia": competencia, "confirmo": "1"})


# ---- fechar --------------------------------------------------------------------------


def test_fechar_grava_a_foto_do_mes_inteiro(admin, banco_exemplo):
    assert _fechar(admin).status_code == 302
    conn = sqlite3.connect(banco_exemplo)
    assert conn.execute("SELECT count(*) FROM fechamento_linhas").fetchone()[0] == 11
    conn.close()
    d = fechamento.diferencas(SISTEMA, "01/2026")
    assert d["diferencas"] == []
    # O resultado da foto é o mesmo do Dashboard de 01/2026.
    assert d["no_fechamento"]["resultado"] == pytest.approx(30000 - 7860 - 3400)
    assert d["no_fechamento"] == d["agora"]


def test_nao_fecha_duas_vezes_nem_sem_confirmar(admin):
    assert admin.post("/fechamento/fechar", data={"competencia": "01/2026"}).status_code == 400
    _fechar(admin)
    assert _fechar(admin).status_code == 400


def test_nao_fecha_mes_futuro(admin):
    assert _fechar(admin, "12/2099").status_code == 400


@pytest.mark.parametrize("perfil", ["financeiro", "leitura"])
def test_so_admin_fecha(banco_exemplo, perfil):
    c = cliente_para(banco_exemplo, perfil=perfil, empresas=("ALFA",))
    assert _fechar(c).status_code == 403
    assert c.get("/fechamento").status_code == 200  # mas vê a lista


# ---- diferenças pós-fechamento --------------------------------------------------------


def test_mudanca_do_tiny_vira_diferenca_com_a_linha(admin, banco_exemplo):
    _fechar(admin)
    # O Tiny mudou o valor da conta 4, criou uma conta nova em 01/2026 e
    # mudou a competência da nota 201 para 02/2026.
    _sql(banco_exemplo, "UPDATE contas_pagar SET valor_centavos = 350000 WHERE id = '4'")
    gravar(
        banco_exemplo, [_conta("ALFA", 70, "COMERCIO-Frete", 100.0, "01/2026", fornecedor="Novo")]
    )
    _sql(banco_exemplo, "UPDATE notas SET competencia = '02/2026' WHERE id = '201'")

    d = fechamento.diferencas(SISTEMA, "01/2026")
    por_chave = {(x["tabela"], x["chave"]): x for x in d["diferencas"]}
    assert por_chave[("conta", "4")]["mudanca"] == "alterada: valor"
    assert por_chave[("conta", "4")]["efeito"] == pytest.approx(500)
    assert por_chave[("conta", "70")]["mudanca"] == "entrou no mês"
    assert por_chave[("nota", "servico:201")]["mudanca"] == "saiu do mês (agora em 02/2026)"
    assert d["efeito_despesa"] == pytest.approx(600)
    assert d["efeito_receita"] == pytest.approx(-20000)
    # O fechado continua lá; o atual reflete o Tiny.
    assert d["no_fechamento"]["receita"] == pytest.approx(30000)
    assert d["agora"]["receita"] == pytest.approx(10000)


def test_mudanca_de_regra_de_exclusao_tambem_aparece(admin, banco_exemplo):
    _fechar(admin)
    _sql(
        banco_exemplo,
        "INSERT INTO regras_exclusao (tipo, valor) VALUES ('categoria_primaria', 'COMERCIO')",
    )
    (dif,) = fechamento.diferencas(SISTEMA, "01/2026")["diferencas"]
    assert dif["mudanca"] == "alterada: considerar" and dif["efeito"] == pytest.approx(-1000)


def test_dashboard_mostra_o_vivo_com_alerta(admin, banco_exemplo):
    from tests.test_telas import _contexto

    _fechar(admin)
    _sql(banco_exemplo, "UPDATE contas_pagar SET valor_centavos = 350000 WHERE id = '4'")
    c = _contexto(admin, "/dashboard?competencia=01/2026")
    assert c["total_despesa"] == pytest.approx(7860 + 500)  # número vivo
    (alerta,) = c["alertas_fechamento"]
    assert alerta["diferencas"] == 1 and alerta["efeito_despesa"] == pytest.approx(500)
    corpo = admin.get("/dashboard?competencia=01/2026").get_data(as_text=True)
    assert "01/2026 fechado" in corpo and "+500,00" in corpo


def test_tela_de_diferencas_e_tabela_filtravel(admin, banco_exemplo):
    _fechar(admin)
    _sql(banco_exemplo, "UPDATE contas_pagar SET valor_centavos = 350000 WHERE id = '4'")
    corpo = admin.get("/fechamento/diferencas?competencia=01/2026").get_data(as_text=True)
    assert "alterada: valor" in corpo and "Linhas que mudaram depois do fechamento (1)" in corpo
    r = admin.get(
        "/api/valores-filtro?tabela=diferencas&coluna=mudanca&competencia=01/2026"
    ).get_json()
    assert r["valores"] == ["alterada: valor"]
    vazio = admin.get("/fechamento/diferencas?competencia=01/2026&mudanca=entrou+no+m%C3%AAs")
    assert "alterada: valor" not in vazio.get_data(as_text=True).split("<tbody>")[-1]


def test_escopo_limita_a_foto_e_as_diferencas(admin, banco_exemplo):
    _fechar(admin)
    _sql(banco_exemplo, "UPDATE contas_pagar SET valor_centavos = 350000 WHERE id = '4'")  # BETA
    alfa = Escopo(usuario_id=9, login="x", perfil="leitura", empresas=frozenset({"ALFA"}))
    d = fechamento.diferencas(alfa, "01/2026")
    assert d["diferencas"] == []
    assert d["no_fechamento"]["receita"] == pytest.approx(10000)  # só a venda da ALFA


# ---- trava dos ajustes manuais ---------------------------------------------------------


def test_mes_fechado_trava_os_ajustes(admin):
    _fechar(admin)
    r = admin.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    assert r.status_code == 409 and "01/2026 fechada" in r.get_json()["erro"]
    r = admin.post(
        "/receitas/marcar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "201", "considerar": False},
    )
    assert r.status_code == 409
    # Mover nota de mês aberto PARA dentro do fechado também é recusado.
    r = admin.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "203", "competencia": "01/2026"},
    )
    assert r.status_code == 409
    # Mês aberto segue livre.
    r = admin.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "03/2026"},
    )
    assert r.status_code == 200


def test_sincronizacao_nao_e_travada(admin, banco_exemplo):
    """Espelho do Tiny: a gravação da sincronização passa mesmo com o mês fechado."""
    from app.repositorio_contas_pagar import upsert_contas

    _fechar(admin)
    upsert_contas(SISTEMA, [{**_conta("ALFA", 1, "COMERCIO-Frete", 1234.0, "01/2026")}])
    (dif,) = fechamento.diferencas(SISTEMA, "01/2026")["diferencas"]
    assert dif["chave"] == "1" and dif["mudanca"] == "alterada: valor"


# ---- reabrir ---------------------------------------------------------------------------


def test_reabrir_exige_admin_e_motivo_e_libera(banco_exemplo, admin):
    _fechar(admin)
    fin = cliente_para(banco_exemplo, perfil="financeiro", empresas=("ALFA",))
    assert (
        fin.post(
            "/fechamento/reabrir", data={"competencia": "01/2026", "motivo": "quero"}
        ).status_code
        == 403
    )
    r = admin.post("/fechamento/reabrir", data={"competencia": "01/2026", "motivo": "ok"})
    assert "motivo" in r.headers["Location"].lower() or "erro" in r.headers["Location"]
    assert fechamento.vigentes().get("01/2026") is not None  # continua fechado
    admin.post(
        "/fechamento/reabrir", data={"competencia": "01/2026", "motivo": "nota corrigida no Tiny"}
    )
    assert fechamento.vigentes().get("01/2026") is None
    r = admin.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    assert r.status_code == 200
    # E pode fechar de novo: o histórico guarda os dois.
    _fechar(admin)
    assert len(fechamento.historico("01/2026")) == 2


def test_fechar_e_reabrir_ficam_na_auditoria(admin, banco_exemplo):
    _fechar(admin)
    admin.post(
        "/fechamento/reabrir", data={"competencia": "01/2026", "motivo": "nota corrigida no Tiny"}
    )
    conn = sqlite3.connect(banco_exemplo)
    acoes = [
        r[0]
        for r in conn.execute(
            "SELECT acao FROM auditoria WHERE entidade = 'fechamento' ORDER BY id"
        )
    ]
    conn.close()
    assert acoes == ["fechar", "reabrir"]


# ---- imutabilidade da foto -------------------------------------------------------------


@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE fechamento_linhas SET valor_centavos = 1",
        "DELETE FROM fechamento_linhas",
        "DELETE FROM fechamentos",
        "UPDATE fechamentos SET resumo = '{}'",
        "UPDATE fechamentos SET competencia = '02/2026'",
    ],
)
def test_foto_do_fechamento_e_imutavel(admin, banco_exemplo, comando):
    _fechar(admin)
    with pytest.raises(sqlite3.IntegrityError):
        _sql(banco_exemplo, comando)


def test_reabertura_so_uma_vez(admin, banco_exemplo):
    _fechar(admin)
    admin.post(
        "/fechamento/reabrir", data={"competencia": "01/2026", "motivo": "nota corrigida no Tiny"}
    )
    with pytest.raises(sqlite3.IntegrityError):
        _sql(banco_exemplo, "UPDATE fechamentos SET motivo_reabertura = 'outro motivo qualquer'")
