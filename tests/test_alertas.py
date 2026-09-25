"""Alertas de anomalia (Fase 4.5), com bancos sintéticos montados caso a caso.

Cada regra é testada no limite (dentro/fora da janela, acima/abaixo do piso),
porque o valor do alerta está justamente em não gritar à toa: no banco real a
regra ingênua de duplicidade dava mais de mil pares.
"""

import sqlite3
from datetime import date

import pytest

from financeiro import alertas
from financeiro.escopo import SISTEMA
from tests.conftest import _conta, cliente_para, gravar

HOJE = date(2026, 9, 25)


def _c(empresa, id_, valor, venc, competencia, historico="Ref. NF 1", **extra):
    """Conta com histórico (o _conta do conftest grava histórico vazio)."""
    linha = _conta(empresa, id_, extra.pop("categoria", "OBRA X-Material"), valor, competencia,
                   data_vencimento=venc, **extra)  # fmt: skip
    linha["historico"] = historico
    return linha


def _tipo(lista, tipo):
    return [a for a in lista if a["tipo"] == tipo]


def _param(caminho, chave, valor):
    conn = sqlite3.connect(caminho)
    conn.execute("UPDATE parametros_alerta SET valor = ? WHERE chave = ?", (valor, chave))
    conn.commit()
    conn.close()


# ---- duplicidade ---------------------------------------------------------------------


def test_duplicado_mesmo_fornecedor_valor_historico_e_vencimento_proximo(banco):
    gravar(banco, [
        _c("ALFA", 1, 1500.0, "10/03/2026", "03/2026", fornecedor="Loja"),
        _c("ALFA", 2, 1500.0, "12/03/2026", "03/2026", fornecedor="Loja"),
    ])  # fmt: skip
    [a] = _tipo(alertas.calcular(SISTEMA, HOJE), "duplicado")
    assert a["chave"] == "duplicado:ALFA:1+2"
    assert a["valor"] == 1500  # o que se pagaria a mais
    assert a["filtros"]["data_vencimento"] == ["10/03/2026", "12/03/2026"]


def test_historico_diferente_nao_e_duplicidade_mas_a_exigencia_e_configuravel(banco):
    # O caso real: mesmo fornecedor e valor, placas de veículo diferentes.
    gravar(banco, [
        _c("ALFA", 1, 800.0, "10/03/2026", "03/2026", historico="Frete placa ABC1D23"),
        _c("ALFA", 2, 800.0, "10/03/2026", "03/2026", historico="Frete placa XYZ9K87"),
    ])  # fmt: skip
    assert _tipo(alertas.calcular(SISTEMA, HOJE), "duplicado") == []
    _param(banco, "duplicado_exigir_historico_igual", 0)
    assert len(_tipo(alertas.calcular(SISTEMA, HOJE), "duplicado")) == 1


def test_historico_compara_sem_espaco_e_sem_caixa(banco):
    gravar(banco, [
        _c("ALFA", 1, 800.0, "10/03/2026", "03/2026", historico="Ref.  NF 10\n"),
        _c("ALFA", 2, 800.0, "10/03/2026", "03/2026", historico="REF. NF 10"),
    ])  # fmt: skip
    assert len(_tipo(alertas.calcular(SISTEMA, HOJE), "duplicado")) == 1


def test_janela_de_vencimento_e_limite(banco):
    gravar(banco, [
        _c("ALFA", 1, 800.0, "01/03/2026", "03/2026"),
        _c("ALFA", 2, 800.0, "08/03/2026", "03/2026"),  # 7 dias: dentro
        _c("ALFA", 3, 800.0, "16/03/2026", "03/2026"),  # 8 dias do anterior: fora
    ])  # fmt: skip
    [a] = _tipo(alertas.calcular(SISTEMA, HOJE), "duplicado")
    assert a["chave"] == "duplicado:ALFA:1+2"


def test_tres_iguais_sao_um_alerta_com_duas_vezes_o_valor(banco):
    gravar(banco, [_c("ALFA", i, 100.0, "10/03/2026", "03/2026") for i in (1, 2, 3)])
    [a] = _tipo(alertas.calcular(SISTEMA, HOJE), "duplicado")
    assert a["valor"] == 200 and a["chave"] == "duplicado:ALFA:1+2+3"


def test_duplicidade_ignora_desconsiderada_e_competencia_fora_da_visao(banco):
    gravar(banco, [
        _c("ALFA", 1, 100.0, "10/03/2026", "03/2026"),
        _c("ALFA", 2, 100.0, "10/03/2026", "03/2026", considerar_manual=0),
        _c("ALFA", 3, 100.0, "10/12/2025", "12/2025"),
        _c("ALFA", 4, 100.0, "10/12/2025", "12/2025"),
    ])  # fmt: skip
    assert _tipo(alertas.calcular(SISTEMA, HOJE), "duplicado") == []


# ---- fornecedor novo -------------------------------------------------------------------


def test_fornecedor_novo_acima_do_piso(banco):
    gravar(banco, [
        _c("ALFA", 1, 3000.0, "30/09/2026", "09/2026", fornecedor="Novo", data_emissao="01/09/2026"),
        _c("ALFA", 2, 2500.0, "30/10/2026", "10/2026", fornecedor="Novo", data_emissao="01/09/2026",
           historico="outra"),
    ])  # fmt: skip
    [a] = _tipo(alertas.calcular(SISTEMA, HOJE), "fornecedor_novo")
    assert a["valor"] == 5500 and a["competencia"] == "09/2026"  # total, não a maior conta
    assert "01/09/2026" in a["detalhe"]


def test_fornecedor_com_historico_antigo_nao_e_novo(banco):
    # O lançamento de 2025 está fora da visão, mas conta para "novo": o
    # fornecedor já trabalhava com a empresa.
    gravar(banco, [
        _c("ALFA", 1, 9000.0, "30/09/2026", "09/2026", fornecedor="Antigo", data_emissao="01/09/2026"),
        _c("ALFA", 2, 10.0, "30/03/2025", "03/2025", fornecedor="Antigo", data_emissao="01/03/2025"),
    ])  # fmt: skip
    assert _tipo(alertas.calcular(SISTEMA, HOJE), "fornecedor_novo") == []


def test_fornecedor_novo_abaixo_do_piso_ou_fora_da_janela(banco):
    gravar(banco, [
        _c("ALFA", 1, 4999.0, "30/09/2026", "09/2026", fornecedor="Pequeno", data_emissao="20/09/2026"),
        _c("ALFA", 2, 9000.0, "30/09/2026", "09/2026", fornecedor="Velho", data_emissao="01/07/2026"),
    ])  # fmt: skip
    assert _tipo(alertas.calcular(SISTEMA, HOJE), "fornecedor_novo") == []


# ---- categoria contra a média de 3 meses ------------------------------------------------


def _serie(valores: dict[str, float], categoria="OBRA X-Material", empresa="ALFA"):
    return [
        _c(empresa, f"{empresa}{i}", v, f"10/{m}", m, historico=m, categoria=categoria,
           fornecedor=f"F{i}", data_emissao="01/01/2024")
        for i, (m, v) in enumerate(valores.items())
    ]  # fmt: skip


def test_categoria_acima_da_media_de_3_meses(banco):
    gravar(banco, _serie({"01/2026": 10000, "02/2026": 10000, "03/2026": 10000, "04/2026": 40000}))
    lista = _tipo(alertas.calcular(SISTEMA, HOJE), "categoria")
    a = next(a for a in lista if a["competencia"] == "04/2026")
    assert (a["valor"], a["descricao"]) == (40000, "OBRA X")
    assert "+300%" in a["detalhe"]
    # O mês seguinte ao pico (zero contra média de 20 mil) também está fora do
    # padrão; de 06/2026 em diante a média já não sustenta a diferença mínima.
    assert sorted(a["competencia"] for a in lista) == ["04/2026", "05/2026"]


def test_categoria_abaixo_do_piso_em_reais_nao_alerta(banco):
    # +150%, mas só R$ 15 mil de diferença (piso padrão: R$ 20 mil).
    gravar(banco, _serie({"01/2026": 10000, "02/2026": 10000, "03/2026": 10000, "04/2026": 25000}))
    assert _tipo(alertas.calcular(SISTEMA, HOJE), "categoria") == []


def test_queda_tambem_alerta_e_mes_corrente_nao_entra(banco):
    gravar(banco, _serie({"01/2026": 50000, "02/2026": 50000, "03/2026": 50000, "04/2026": 0.01}))
    assert "04/2026" in [
        a["competencia"] for a in _tipo(alertas.calcular(SISTEMA, HOJE), "categoria")
    ]
    # Com "hoje" em abril, abril está em andamento: não é avaliado.
    assert _tipo(alertas.calcular(SISTEMA, date(2026, 4, 20)), "categoria") == []


# ---- escopo, dispensa, parâmetros e telas -------------------------------------------------


@pytest.fixture
def com_duplicados(banco):
    gravar(banco, [
        _c("ALFA", 1, 100.0, "10/03/2026", "03/2026"),
        _c("ALFA", 2, 100.0, "10/03/2026", "03/2026"),
        _c("BETA", 3, 100.0, "10/03/2026", "03/2026"),
        _c("BETA", 4, 100.0, "10/03/2026", "03/2026"),
    ])  # fmt: skip
    return banco


def test_escopo(com_duplicados):
    c = cliente_para(com_duplicados, perfil="leitura", empresas=("ALFA",))
    html = c.get("/alertas").get_data(as_text=True)
    assert "Possível duplicidade" in html
    assert "BETA" not in html


def test_dispensar_e_reativar_com_auditoria(com_duplicados):
    c = cliente_para(com_duplicados)
    chave = "duplicado:ALFA:1+2"
    # Sem motivo: volta com o aviso na tela, nada gravado.
    r = c.post("/alertas/dispensar", data={"chave": chave, "motivo": "ok"})
    assert r.status_code == 302 and "erro=" in r.headers["Location"]
    r = c.post(
        "/alertas/dispensar?situacao=ativo", data={"chave": chave, "motivo": "duas NFs distintas"}
    )
    assert r.status_code == 302 and "situacao=ativo" in r.headers["Location"]  # filtros preservados
    a = next(a for a in alertas.calcular(SISTEMA, HOJE) if a["chave"] == chave)
    assert (a["situacao"], a["motivo"]) == ("dispensado", "duas NFs distintas")
    assert c.post("/alertas/reativar", data={"chave": chave}).status_code == 302
    a = next(a for a in alertas.calcular(SISTEMA, HOJE) if a["chave"] == chave)
    assert a["situacao"] == "ativo"
    conn = sqlite3.connect(com_duplicados)
    acoes = [r[0] for r in conn.execute("SELECT acao FROM auditoria WHERE entidade = 'alerta'")]
    conn.close()
    assert acoes == ["dispensar_alerta", "reativar_alerta"]


def test_dispensar_fora_do_escopo_ou_inventado_e_404_e_leitura_e_403(com_duplicados):
    fin = cliente_para(com_duplicados, perfil="financeiro", empresas=("ALFA",))
    dados = {"chave": "duplicado:BETA:3+4", "motivo": "tentativa"}
    assert fin.post("/alertas/dispensar", data=dados).status_code == 404
    dados["chave"] = "duplicado:ALFA:9+9"
    assert fin.post("/alertas/dispensar", data=dados).status_code == 404
    leitura = cliente_para(com_duplicados, perfil="leitura", empresas=("ALFA",))
    dados["chave"] = "duplicado:ALFA:1+2"
    assert leitura.post("/alertas/dispensar", data=dados).status_code == 403


def test_limites_so_admin_com_faixa_e_auditoria(com_duplicados):
    admin = cliente_para(com_duplicados)
    form = {
        "duplicado_janela_dias": "3",
        "duplicado_exigir_historico_igual": "1",
        "fornecedor_novo_dias": "45",
        "fornecedor_novo_valor_minimo_centavos": "10.000,00",
        "categoria_variacao_pct": "50",
        "categoria_variacao_valor_minimo_centavos": "20.000,00",
    }
    assert admin.post("/configuracoes/alertas", data=form).status_code == 302
    p = alertas.parametros()
    assert (p["duplicado_janela_dias"], p["fornecedor_novo_dias"]) == (3, 45)
    assert p["fornecedor_novo_valor_minimo_centavos"] == 1_000_000
    # Janela de um mês pegaria a conta mensal: recusada, nada gravado.
    r = admin.post("/configuracoes/alertas", data=dict(form, duplicado_janela_dias="31"))
    assert r.status_code == 400 and alertas.parametros()["duplicado_janela_dias"] == 3
    conn = sqlite3.connect(com_duplicados)
    mudancas = conn.execute(
        "SELECT count(*) FROM auditoria WHERE acao = 'alterar_parametro_alerta'"
    ).fetchone()[0]
    conn.close()
    assert mudancas == 3  # janela, dias e piso; o resto não mudou
    fin = cliente_para(com_duplicados, perfil="financeiro", empresas=("ALFA",))
    assert fin.get("/configuracoes/alertas").status_code == 403


def test_telas_filtro_exportacao_e_cartao_de_pendencias(com_duplicados):
    c = cliente_para(com_duplicados)
    assert c.get("/alertas?tipo_rotulo=Possível duplicidade&empresa=BETA").status_code == 200
    r = c.get("/api/valores-filtro?tabela=alertas&coluna=empresa")
    assert r.status_code == 200
    r = c.get("/alertas?formato=xlsx")
    assert r.status_code == 200 and r.mimetype.endswith("sheet")
    html = c.get("/pendencias").get_data(as_text=True)
    assert "Alertas de anomalia" in html and "Possível duplicidade" in html
