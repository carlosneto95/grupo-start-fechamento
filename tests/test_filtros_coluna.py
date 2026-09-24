"""Funil de coluna estilo Excel: valores(), cascata e rota /api/valores-filtro.

Regras do CLAUDE.md que estes testes prendem:
  - a lista vem em cascata (só o que existe no recorte das OUTRAS colunas);
  - o funil da coluna X ignora o filtro da própria X;
  - valor já marcado aparece sempre, mesmo sem linha por trás;
  - data e competência vêm em árvore Ano › Mês › Dia;
  - lista simples é cortada em LIMITE itens, com aviso de truncado.
"""

from app import filtros_coluna
from app.filtros_coluna import LIMITE, valores
from app.visao import SEM_VALOR


def _linhas(**colunas):
    """Monta linhas a partir de listas paralelas: _linhas(empresa=["A","B"])."""
    n = len(next(iter(colunas.values())))
    return [{c: v[i] for c, v in colunas.items()} for i in range(n)]


# ---- valores(): a função pura --------------------------------------------


def test_lista_distinta_e_ordenada_sem_diferenciar_caixa():
    linhas = _linhas(fornecedor=["beta", "Alfa", "beta", "Gama"])
    r = valores("despesas", "fornecedor", linhas)
    assert r == {
        "tipo": "lista",
        "valores": ["Alfa", "beta", "Gama"],
        "total": 3,
        "truncado": False,
    }


def test_celula_vazia_vira_rotulo_vazio_no_fim():
    linhas = _linhas(fornecedor=["B", None, "  ", "A"])
    r = valores("despesas", "fornecedor", linhas)
    assert r["valores"] == ["A", "B", SEM_VALOR]
    assert r["total"] == 3


def test_marcado_sem_linha_por_tras_continua_na_lista():
    # Sem isso o valor filtraria em silêncio e a tabela ficaria vazia sem explicação.
    r = valores("despesas", "fornecedor", _linhas(fornecedor=["A"]), selecionados=["Z", SEM_VALOR])
    assert r["valores"] == ["A", "Z", SEM_VALOR]


def test_busca_filtra_sem_diferenciar_caixa():
    linhas = _linhas(fornecedor=["Transportes A", "Loja B", "TRANSPORTES C"])
    r = valores("despesas", "fornecedor", linhas, busca="transp")
    assert r["valores"] == ["Transportes A", "TRANSPORTES C"]


def test_lista_longa_e_cortada_com_aviso():
    linhas = _linhas(fornecedor=[f"F{i:04d}" for i in range(LIMITE + 10)])
    r = valores("despesas", "fornecedor", linhas)
    assert len(r["valores"]) == LIMITE
    assert r["total"] == LIMITE + 10
    assert r["truncado"] is True


def test_valor_e_considerar_saem_no_formato_da_celula():
    linhas = [
        {"valor": 1234.5, "considerar_efetivo": True},
        {"valor": None, "considerar_efetivo": False},
    ]
    assert valores("despesas", "valor", linhas)["valores"] == ["1.234,50", SEM_VALOR]
    assert valores("despesas", "considerar_efetivo", linhas)["valores"] == [
        "Considerar",
        "Desconsiderar",
    ]


def test_data_vem_em_arvore_ano_mes_dia():
    linhas = _linhas(data_vencimento=["05/08/2026", "01/08/2026", "31/12/2025", None])
    r = valores("despesas", "data_vencimento", linhas)
    assert r["tipo"] == "arvore"
    anos = r["arvore"]
    assert [a["valor"] for a in anos] == ["2025", "2026", SEM_VALOR]
    agosto = anos[1]["filhos"][0]
    assert agosto["valor"] == "08/2026" and agosto["rotulo"] == "Agosto"
    assert [d["valor"] for d in agosto["filhos"]] == ["01/08/2026", "05/08/2026"]


def test_competencia_para_no_mes_e_aceita_sujeira():
    # Mês inválido e ano absurdo (sujeira do ERP) aparecem, sem quebrar.
    linhas = _linhas(competencia=["08/2026", "13/2026", "07/2800", "abc"])
    arvore = valores("despesas", "competencia", linhas)["arvore"]
    rotulos = {(n["valor"], n["rotulo"]) for n in arvore}
    assert ("abc", "abc") in rotulos  # fora do formato: folha na raiz
    ano_2026 = next(n for n in arvore if n["valor"] == "2026")
    assert [(m["valor"], m["rotulo"]) for m in ano_2026["filhos"]] == [
        ("08/2026", "Agosto"),
        ("13/2026", "13"),
    ]
    assert all(m["filhos"] == [] for m in ano_2026["filhos"])


def test_coluna_nao_filtravel_e_recusada():
    import pytest

    with pytest.raises(ValueError):
        valores("despesas", "historico", [])
    with pytest.raises(ValueError):
        valores("receitas_vendas", "tipo_nota", [])  # constante na tela, sem funil


def test_telas_de_receita_tem_chave_propria():
    assert "tipo_nota" not in filtros_coluna.COLUNAS["receitas_vendas"]
    assert filtros_coluna.COLUNAS["receitas_vendas"] == filtros_coluna.COLUNAS["receitas_servicos"]


# ---- cascata pela rota ----------------------------------------------------


def _api(cliente, **params):
    r = cliente.get("/api/valores-filtro", query_string=params)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_cascata_restringe_pela_outra_coluna(cliente):
    todos = _api(cliente, tabela="despesas", coluna="fornecedor")["valores"]
    so_alfa = _api(cliente, tabela="despesas", coluna="fornecedor", empresa="ALFA")["valores"]
    assert "Loja D" in todos  # fornecedor da BETA
    assert "Loja D" not in so_alfa  # sumiu com empresa=ALFA
    assert "Transportes A" in so_alfa


def test_funil_ignora_o_filtro_da_propria_coluna(cliente):
    # Com empresa=ALFA marcado, o funil de Empresa ainda oferece BETA — senão
    # nunca mais daria para acrescentar outra empresa.
    r = _api(cliente, tabela="despesas", coluna="empresa", empresa="ALFA")
    assert r["valores"] == ["ALFA", "BETA"]


def test_cascata_respeita_o_ano_minimo(cliente):
    # A conta de 12/2025 existe no banco, mas não na visão.
    r = _api(cliente, tabela="despesas", coluna="competencia")
    anos = [n["valor"] for n in r["arvore"]]
    assert "2025" not in anos


def test_nota_sem_competencia_aparece_como_vazio(cliente):
    # Serviço sem competência não some: aparece como "(vazio)" para ser preenchido.
    r = _api(cliente, tabela="receitas_servicos", coluna="competencia_efetiva")
    assert r["arvore"][-1]["valor"] == SEM_VALOR


def test_tabela_ou_coluna_invalida_devolve_400(cliente):
    assert cliente.get("/api/valores-filtro?tabela=xpto&coluna=a").status_code == 400
    assert cliente.get("/api/valores-filtro?tabela=despesas&coluna=historico").status_code == 400


def test_ordem_nao_depende_do_acaso_quando_so_a_caixa_muda():
    """Correção da Fase 1: "Fulano" e "FULANO" empatam no casefold; o desempate
    pelo texto cru dá sempre a mesma ordem, qualquer que seja a do conjunto."""
    import random

    nomes = ["fulano", "Fulano", "FULANO", "Beltrano", "BELTRANO"]
    esperado = ["BELTRANO", "Beltrano", "FULANO", "Fulano", "fulano"]
    for _ in range(20):
        random.shuffle(nomes)
        assert valores("despesas", "fornecedor", _linhas(fornecedor=nomes))["valores"] == esperado
