"""Job único de sincronização (Fase 1, etapa D), com uma API do Tiny FALSA.

Nenhum teste chama a API real: a `fabrica_cliente` do job é trocada por um
cliente em memória que devolve contas e notas sintéticas.
"""

import sqlite3
from datetime import date

import pytest

from app import sincronizar_tudo, trava
from app.config.companies import CompanyConfig

PERIODO = (date(2025, 11, 1), date(2027, 2, 28))


class ClienteFalso:
    """Imita o TinyAPIClient no que o job usa."""

    def __init__(self, conecta=True, quebra_em=None, token_no_erro=None):
        self.conecta = conecta
        self.quebra_em = quebra_em
        self.token_no_erro = token_no_erro

    def testar_conexao(self):
        return self.conecta

    # ---- contas
    def listar_resumo(self, ini, fim, progresso=None, por=()):
        if self.quebra_em == "contas":
            raise RuntimeError(f"falha na API token={self.token_no_erro}")
        return {"501": {"id": "501", "valor": "10.50", "saldo": "0", "situacao": "pago"}}

    def obter_conta_pagar(self, id_conta):
        return {
            "id": id_conta,
            "cliente": {"nome": "Fornecedor Sintético"},
            "valor": "10.50",
            "saldo": "0",
            "situacao": "pago",
            "categoria": "COMERCIO-Frete",
            "competencia": "01/2026",
            "vencimento": "10/01/2026",
            "data": "05/01/2026",
        }

    # ---- notas
    def listar_notas_venda(self, ini, fim):
        if self.quebra_em == "notas":
            raise RuntimeError("falha nas notas")
        return [
            {
                "id": "9001",
                "numero": "1",
                "data_emissao": "15/01/2026",
                "valor": "99.90",
                "descricao_situacao": "Autorizada",
            }
        ]

    def listar_notas_servico(self, ini, fim):
        return []

    def obter_nota_venda(self, id_nota):
        return {"cliente": {"nome": "Cliente Sintético"}}


def _empresa(nome, token="t" * 40):
    return CompanyConfig(key=nome, nome=nome, tiny_api_token=token, tiny_user=None, tiny_pass=None)


def _historico(caminho):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    linhas = [dict(r) for r in conn.execute("SELECT * FROM sincronizacoes ORDER BY id")]
    conn.close()
    return linhas


def _rodar(empresas, clientes, origem="cli", tipos=sincronizar_tudo.TIPOS):
    pedido = sincronizar_tudo.Pedido(empresas=empresas, periodo=PERIODO, origem=origem, tipos=tipos)
    return sincronizar_tudo.executar(pedido, fabrica_cliente=lambda e: clientes[e.nome])


def test_contas_e_notas_no_mesmo_job_com_historico(banco):
    resultados = _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso()})
    assert [(r.tipo, r.status) for r in resultados] == [("contas", "ok"), ("notas", "ok")]

    conn = sqlite3.connect(banco)
    assert conn.execute("SELECT valor_centavos FROM contas_pagar").fetchone()[0] == 1050
    assert conn.execute("SELECT valor_centavos FROM notas").fetchone()[0] == 9990
    conn.close()

    h = _historico(banco)
    assert [(l["empresa"], l["tipo"], l["status"], l["origem"]) for l in h] == [
        ("ALFA", "contas", "ok", "cli"),
        ("ALFA", "notas", "ok", "cli"),
    ]
    assert h[0]["lote"] == h[1]["lote"] and h[0]["terminada_em"]
    assert (h[0]["encontradas"], h[0]["novas"]) == (1, 1)


def test_falha_numa_empresa_nao_derruba_as_outras(banco):
    resultados = _rodar(
        [_empresa("ALFA"), _empresa("BETA")],
        {"ALFA": ClienteFalso(quebra_em="contas"), "BETA": ClienteFalso()},
    )
    status = {(r.empresa, r.tipo): r.status for r in resultados}
    assert status == {
        ("ALFA", "contas"): "erro",
        ("ALFA", "notas"): "ok",  # a outra parte da mesma empresa segue
        ("BETA", "contas"): "ok",
        ("BETA", "notas"): "ok",
    }


def test_erro_gravado_sem_token(banco):
    segredo = "a1b2c3d4" * 6
    _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso(quebra_em="contas", token_no_erro=segredo)})
    erro = _historico(banco)[0]["erro"]
    assert "RuntimeError" in erro and segredo not in erro


def test_sem_conexao_registra_os_dois_tipos(banco):
    _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso(conecta=False)})
    assert [(l["tipo"], l["status"]) for l in _historico(banco)] == [
        ("contas", "erro"),
        ("notas", "erro"),
    ]


def test_empresa_sem_token_nao_chama_a_api(banco):
    resultados = _rodar([_empresa("ALFA", token=None)], {})
    assert {r.erro for r in resultados} == {"sem token de API no .env"}


def test_trava_impede_duas_execucoes_da_mesma_empresa(banco):
    with trava.adquirir("ALFA"):
        resultados = _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso()})
    assert all(r.status == "erro" and "em andamento" in r.erro for r in resultados)
    # E a trava é liberada no fim: a próxima execução roda.
    assert all(r.status == "ok" for r in _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso()}))


def test_so_notas(banco):
    resultados = _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso()}, tipos=("notas",))
    assert [r.tipo for r in resultados] == ["notas"]


def test_ultimas_mostra_ultimo_sucesso_mesmo_depois_de_uma_falha(banco):
    _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso()})
    _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso(quebra_em="contas")})
    contas = next(u for u in sincronizar_tudo.ultimas() if u["tipo"] == "contas")
    assert contas["ultimo_status"] == "erro"
    assert contas["ultimo_sucesso"] is not None


@pytest.mark.parametrize("campo, valor", [("origem", "manual"), ("tipos", ("xpto",))])
def test_pedido_invalido_e_recusado(campo, valor):
    base = {"empresas": [], "periodo": PERIODO, "origem": "cli"}
    base[campo] = valor
    with pytest.raises(ValueError):
        sincronizar_tudo.Pedido(**base)


def test_tela_de_sincronizar_mostra_historico(cliente, monkeypatch):
    # As empresas vêm do .env da máquina; o teste fixa as suas para não
    # depender de onde roda (o CI não tem .env).
    import app.web.extracao as tela

    monkeypatch.setattr(tela, "load_companies", lambda: [_empresa("ALFA")])
    _rodar([_empresa("ALFA")], {"ALFA": ClienteFalso(quebra_em="notas")})
    corpo = cliente.get("/extracao").get_data(as_text=True)
    assert "ALFA · despesas" in corpo and "ALFA · receitas" in corpo
    assert "última tentativa falhou" in corpo
    assert 'value="TODAS"' in corpo
