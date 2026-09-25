"""Estrutura da Fase 1: fábrica, configuração, rotas, erros e log.

O golden master cobre os NÚMEROS das telas; aqui fica o que ele não vê —
toda rota responde, erro não vaza detalhe, a chave curta impede subir e o
log não grava segredo.
"""

import logging

import pytest

from financeiro import configuracao, registro
from tests.conftest import CHAVE_TESTE, cliente_para


def test_sem_chave_o_app_nao_sobe(banco):
    from financeiro import criar_app

    with pytest.raises(RuntimeError, match="GSF_SECRET_KEY"):
        criar_app({"SECRET_KEY": "curta", "CAMINHO_BANCO": str(banco)})


def test_configuracao_ignora_secret_key_do_ambiente(monkeypatch, tmp_path):
    """No PythonAnywhere o WSGI da conta põe a SECRET_KEY de OUTRO sistema no
    ambiente. Ela não pode ser herdada: só vale GSF_SECRET_KEY."""
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.delenv("GSF_SECRET_KEY", raising=False)
    monkeypatch.setattr(configuracao, "RAIZ", tmp_path)  # sem .env nesta pasta
    with pytest.raises(RuntimeError):
        configuracao.config_flask()


def test_env_do_projeto_vence_o_ambiente(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"GSF_SECRET_KEY={'a' * 40}\nOUTRA=1\n", encoding="utf-8")
    monkeypatch.setenv("GSF_SECRET_KEY", "b" * 40)
    monkeypatch.setattr(configuracao, "ARQUIVO_ENV", tmp_path / ".env")
    v = configuracao.variaveis()
    assert v["GSF_SECRET_KEY"] == "a" * 40
    assert "OUTRA" not in v  # só o prefixo do projeto entra


@pytest.mark.parametrize(
    "rota",
    [
        "/despesas",
        "/dashboard",
        "/receitas/vendas",
        "/receitas/servicos",
        "/analise-receitas",
        "/extracao",
        "/configuracoes/exclusoes",
        "/extracao/status",
        "/api/valores-filtro?tabela=despesas&coluna=empresa",
    ],
)
def test_toda_tela_responde(cliente, rota):
    assert cliente.get(rota).status_code == 200


@pytest.mark.parametrize(
    "antigo, novo",
    [("/", "/despesas"), ("/contas-pagar", "/despesas"), ("/receitas", "/receitas/vendas")],
)
def test_enderecos_antigos_redirecionam(cliente, antigo, novo):
    r = cliente.get(antigo)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(novo)


def test_404_e_generico(cliente):
    r = cliente.get("/nao-existe")
    assert r.status_code == 404
    assert "Página não encontrada" in r.get_data(as_text=True)


def test_erro_interno_nao_mostra_detalhe(banco):
    cliente = cliente_para(banco, PROPAGATE_EXCEPTIONS=False)

    @cliente.application.route("/explode")
    def explode():
        raise ValueError("SELECT segredo FROM tabela token=abcdef")

    r = cliente.get("/explode")
    corpo = r.get_data(as_text=True)
    assert r.status_code == 500
    assert "segredo" not in corpo and "Traceback" not in corpo and "SELECT" not in corpo


def test_marcar_e_ajustar_gravam(cliente):
    r = cliente.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    assert r.get_json() == {"ok": True}
    r = cliente.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "03/2026"},
    )
    assert r.get_json() == {"ok": True}


# ---- log ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, proibido",
    [
        ("url https://api.tiny.com.br/x?token=abc123curto&formato=json", "abc123curto"),
        ("token solto " + "f" * 64, "f" * 64),
        ("cliente 123.456.789-09 na nota", "123.456.789-09"),
        ("cnpj 12.345.678/0001-90 na nota", "12.345.678/0001-90"),
        ("cnpj cru 12345678000190", "12345678000190"),
        ("{'senha': 'minha-senha'}", "minha-senha"),
    ],
)
def test_log_mascara_segredo_e_documento(entrada, proibido):
    assert proibido not in registro.mascarar(entrada)


def test_filtro_do_log_mascara_traceback(tmp_path):
    log = logging.getLogger("financeiro.teste_mascara")
    handler = logging.FileHandler(tmp_path / "t.log", encoding="utf-8")
    handler.addFilter(registro.FiltroSigilo())
    log.addHandler(handler)
    try:
        raise RuntimeError("falhou com token=" + "z" * 40)
    except RuntimeError:
        log.exception("erro na chamada %s", "cpf 111.222.333-44")
    handler.close()
    texto = (tmp_path / "t.log").read_text(encoding="utf-8")
    assert "z" * 40 not in texto and "111.222.333-44" not in texto
    assert "RuntimeError" in texto  # o traceback continua útil


def test_chave_de_teste_tem_tamanho_minimo():
    assert len(CHAVE_TESTE) >= configuracao.TAMANHO_MINIMO_CHAVE
