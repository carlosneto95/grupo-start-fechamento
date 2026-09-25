"""Revisão de segurança da Fase 2 — cada proteção PROVADA por um teste que
falharia se ela não existisse (adaptado de testes/revisao_seguranca.py do
Novos Convertidos).

Cobre: acesso sem login, acesso a outra empresa, perfil sem permissão, POST
sem CSRF, headers, login (bloqueio, mensagem única, sessão, expiração,
troca obrigatória), open redirect, SQL com nome de coluna, LGPD e validação.
Dados sintéticos: empresas ALFA e BETA do conftest.
"""

import sqlite3
import time

import pytest

from financeiro import escopo as esc
from financeiro.escopo import SISTEMA, Escopo
from tests.conftest import SENHA_TESTE, cliente_para, criar_usuario, entrar

GETS = [
    "/despesas",
    "/dashboard",
    "/receitas/vendas",
    "/receitas/servicos",
    "/analise-receitas",
    "/extracao",
    "/configuracoes/exclusoes",
    "/admin/usuarios",
    "/trocar-senha",
]
POSTS = [
    ("/despesas/marcar", {"empresa": "ALFA", "id": "1", "considerar": False}),
    (
        "/receitas/marcar",
        {"empresa": "ALFA", "tipo_nota": "venda", "id": "101", "considerar": False},
    ),
    (
        "/receitas/ajustar",
        {"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "03/2026"},
    ),
    ("/extracao/iniciar", {"empresa": "TODAS", "ano": 2026}),
]


def _auditoria(caminho, acao=None):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    sql, params = "SELECT * FROM auditoria", ()
    if acao:
        sql, params = sql + " WHERE acao = ?", (acao,)
    linhas = [dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return linhas


# ---- 1. sem login ------------------------------------------------------------------


@pytest.mark.parametrize("rota", GETS + ["/api/valores-filtro?tabela=despesas&coluna=empresa"])
def test_sem_login_nada_abre(banco_exemplo, rota):
    c = cliente_para(banco_exemplo, logado=False)
    r = c.get(rota)
    if rota.startswith("/api/"):
        assert r.status_code == 401
    else:
        assert r.status_code == 302 and "/login" in r.headers["Location"]


@pytest.mark.parametrize("rota, corpo", POSTS)
def test_sem_login_nenhum_post_grava(banco_exemplo, rota, corpo):
    c = cliente_para(banco_exemplo, logado=False)
    assert c.post(rota, json=corpo).status_code == 401
    assert [a for a in _auditoria(banco_exemplo) if a["entidade"] != "usuario"] == []


def test_login_e_css_sao_publicos(banco_exemplo):
    c = cliente_para(banco_exemplo, logado=False)
    assert c.get("/login").status_code == 200
    assert c.get("/static/css/style.css").status_code == 200


# ---- 2. outra empresa ----------------------------------------------------------------


@pytest.fixture
def financeiro_alfa(banco_exemplo):
    return cliente_para(banco_exemplo, perfil="financeiro", empresas=("ALFA",))


def test_listagens_so_trazem_a_empresa_do_escopo(financeiro_alfa):
    from tests.test_telas import _contexto

    assert {c["empresa"] for c in _contexto(financeiro_alfa, "/despesas")["contas"]} == {"ALFA"}
    assert {n["empresa"] for n in _contexto(financeiro_alfa, "/receitas/vendas")["notas"]} <= {
        "ALFA"
    }
    assert _contexto(financeiro_alfa, "/receitas/servicos")["notas"] == []  # serviços são da BETA
    dash = _contexto(financeiro_alfa, "/dashboard?competencia=01/2026")
    assert dash["total_receita"] == pytest.approx(10000)  # só a venda da ALFA
    assert dash["opcoes"]["empresa"] == ["ALFA"]


def test_funil_nao_vaza_valor_de_outra_empresa(financeiro_alfa):
    r = financeiro_alfa.get("/api/valores-filtro?tabela=despesas&coluna=fornecedor").get_json()
    assert "Loja D" not in r["valores"]  # fornecedor da BETA
    r = financeiro_alfa.get("/api/valores-filtro?tabela=despesas&coluna=empresa").get_json()
    assert r["valores"] == ["ALFA"]


def test_escrever_em_outra_empresa_da_404_e_nada_grava(financeiro_alfa, banco_exemplo):
    r = financeiro_alfa.post(
        "/despesas/marcar", json={"empresa": "BETA", "id": "4", "considerar": False}
    )
    assert r.status_code == 404  # 404, e não 403: não confirma que a conta existe
    r = financeiro_alfa.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "03/2026"},
    )
    assert r.status_code == 404
    assert [a for a in _auditoria(banco_exemplo) if a["entidade"] != "usuario"] == []


def test_escrever_na_propria_empresa_funciona(financeiro_alfa, banco_exemplo):
    r = financeiro_alfa.post(
        "/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False}
    )
    assert r.get_json() == {"ok": True}
    (linha,) = _auditoria(banco_exemplo, "marcar")
    assert linha["usuario"] == "teste-financeiro-alfa"


# ---- 3. perfil ----------------------------------------------------------------------


@pytest.mark.parametrize("rota", ["/extracao", "/configuracoes/exclusoes", "/admin/usuarios"])
def test_telas_de_admin_negadas_ao_financeiro(financeiro_alfa, banco_exemplo, rota):
    assert financeiro_alfa.get(rota).status_code == 403
    assert _auditoria(banco_exemplo, "acesso_negado")


def test_financeiro_nao_dispara_sincronizacao(financeiro_alfa):
    assert (
        financeiro_alfa.post(
            "/extracao/iniciar", json={"empresa": "TODAS", "ano": 2026}
        ).status_code
        == 403
    )


def test_leitura_ve_mas_nao_grava(banco_exemplo):
    c = cliente_para(banco_exemplo, perfil="leitura", empresas=("ALFA",))
    assert c.get("/despesas").status_code == 200
    r = c.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    assert r.status_code == 403
    corpo = c.get("/despesas").get_data(as_text=True)
    assert 'data-somente-leitura="1"' in corpo


def test_lista_de_usuarios_nao_existe_para_quem_nao_e_admin(financeiro_alfa):
    r = financeiro_alfa.get("/api/valores-filtro?tabela=usuarios&coluna=login")
    assert r.status_code == 400 and r.get_json() == {"erro": "tabela desconhecida"}


def test_menu_esconde_admin_do_financeiro(financeiro_alfa):
    corpo = financeiro_alfa.get("/despesas").get_data(as_text=True)
    assert "Sincronizar" not in corpo and "Usuários" not in corpo


# ---- 4. CSRF -------------------------------------------------------------------------


@pytest.mark.parametrize("rota, corpo", POSTS)
def test_post_sem_token_csrf_e_recusado(banco_exemplo, rota, corpo):
    c = cliente_para(banco_exemplo, csrf=True)
    r = c.post(rota, json=corpo)
    assert r.status_code == 400
    assert [a for a in _auditoria(banco_exemplo) if a["entidade"] != "usuario"] == []


def test_post_com_token_no_cabecalho_passa(banco_exemplo):
    c = cliente_para(banco_exemplo, csrf=True)
    corpo = c.get("/despesas").get_data(as_text=True)
    token = corpo.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    r = c.post(
        "/despesas/marcar",
        json={"empresa": "ALFA", "id": "1", "considerar": False},
        headers={"X-CSRFToken": token},
    )
    assert r.get_json() == {"ok": True}


def test_login_e_sair_exigem_csrf(banco_exemplo):
    c = cliente_para(banco_exemplo, csrf=True, logado=False)
    with c.application.app_context():
        u = criar_usuario()
    r = c.post("/login", data={"login": u["login"], "senha": SENHA_TESTE})
    assert r.status_code == 400
    entrar(c, u)
    assert c.post("/sair").status_code == 400  # sem token, a sessão não cai
    assert c.get("/despesas").status_code == 200


# ---- 5. headers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rota",
    ["/despesas", "/login", "/nao-existe", "/api/valores-filtro?tabela=despesas&coluna=empresa"],
)
def test_headers_de_seguranca_em_toda_resposta(banco_exemplo, rota):
    c = cliente_para(banco_exemplo)
    h = c.get(rota).headers
    csp = h["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "same-origin"
    assert "max-age=" in h["Strict-Transport-Security"]
    assert h["Cache-Control"] == "no-store"


def test_nenhum_template_tem_script_ou_estilo_inline():
    """A CSP sem 'unsafe-inline' quebraria qualquer um deles em produção."""
    import re
    from pathlib import Path

    for arquivo in Path("templates").glob("*.html"):
        texto = arquivo.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", texto), arquivo
        assert 'style="' not in texto and "<style" not in texto, arquivo
        assert not re.search(r"\son[a-z]+=\"", texto), arquivo


# ---- 6. login ------------------------------------------------------------------------------


@pytest.fixture
def anonimo(banco_exemplo):
    c = cliente_para(banco_exemplo, logado=False)
    with c.application.app_context():
        u = criar_usuario(login="neto")
    return c, u


def _entrar(c, login, senha):
    return c.post("/login", data={"login": login, "senha": senha})


def test_login_certo_abre_sessao(anonimo):
    c, u = anonimo
    r = _entrar(c, "neto", SENHA_TESTE)
    assert r.status_code == 302
    assert c.get("/despesas").status_code == 200


def test_mensagem_igual_para_login_inexistente_e_senha_errada(anonimo):
    c, _ = anonimo
    a = _entrar(c, "neto", "SenhaErrada123").get_data(as_text=True)
    b = _entrar(c, "ninguem", "SenhaErrada123").get_data(as_text=True)
    assert "Usuário ou senha inválidos." in a and "Usuário ou senha inválidos." in b


def test_bloqueio_apos_5_erros_mesmo_com_a_senha_certa(anonimo, banco_exemplo):
    c, _ = anonimo
    for _ in range(5):
        _entrar(c, "neto", "SenhaErrada123")
    r = _entrar(c, "neto", SENHA_TESTE)
    assert r.status_code == 401 and "bloqueado" in r.get_data(as_text=True)
    assert _auditoria(banco_exemplo, "login_bloqueou")
    # Passados os 15 minutos, volta a entrar.
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("UPDATE usuarios SET bloqueado_ate = '2000-01-01T00:00:00' WHERE login = 'neto'")
    conn.commit()
    conn.close()
    assert _entrar(c, "neto", SENHA_TESTE).status_code == 302


def test_senha_gravada_so_como_hash_scrypt(anonimo, banco_exemplo):
    conn = sqlite3.connect(banco_exemplo)
    (hash_,) = conn.execute("SELECT senha_hash FROM usuarios WHERE login = 'neto'").fetchone()
    conn.close()
    assert hash_.startswith("scrypt:") and SENHA_TESTE not in hash_


def test_login_e_falha_ficam_na_auditoria(anonimo, banco_exemplo):
    c, _ = anonimo
    _entrar(c, "neto", "SenhaErrada123")
    _entrar(c, "neto", SENHA_TESTE)
    acoes = [a["acao"] for a in _auditoria(banco_exemplo) if a["entidade"] == "usuario"]
    assert "login_falhou" in acoes and "login" in acoes


@pytest.mark.parametrize(
    "proximo, esperado",
    [
        ("/dashboard", "/dashboard"),
        ("https://site-falso.com/x", "/despesas"),
        ("//site-falso.com", "/despesas"),
    ],
)
def test_sem_open_redirect(anonimo, proximo, esperado):
    c, _ = anonimo
    r = c.post(f"/login?proximo={proximo}", data={"login": "neto", "senha": SENHA_TESTE})
    assert r.headers["Location"].endswith(esperado)


# ---- 7. sessão -----------------------------------------------------------------------------


def test_cookie_com_nome_proprio_e_flags(banco_exemplo):
    c = cliente_para(banco_exemplo, logado=False, SESSION_COOKIE_SECURE=True)
    with c.application.app_context():
        criar_usuario(login="neto")
    cookie = _entrar(c, "neto", SENHA_TESTE).headers["Set-Cookie"]
    assert cookie.startswith("gsf_sessao=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_sessao_expira_apos_60_minutos_parada(banco_exemplo):
    c = cliente_para(banco_exemplo)
    with c.session_transaction() as s:
        s["ultimo"] = int(time.time()) - 61 * 60
    r = c.get("/despesas")
    assert r.status_code == 302 and "expirou=1" in r.headers["Location"]


def test_mudar_perfil_derruba_a_sessao_na_hora(banco_exemplo):
    c = cliente_para(banco_exemplo, perfil="financeiro", empresas=("ALFA",))
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("UPDATE usuarios SET sessao_versao = sessao_versao + 1")
    conn.commit()
    conn.close()
    assert c.get("/despesas").status_code == 302


def test_perfil_vem_do_banco_e_nao_do_cookie(banco_exemplo):
    """Rebaixar no banco vale na próxima requisição, mesmo com o cookie antigo."""
    c = cliente_para(banco_exemplo)  # admin
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("UPDATE usuarios SET perfil = 'leitura'")
    conn.execute(
        "INSERT INTO usuario_empresa (usuario_id, empresa) SELECT id, 'ALFA' FROM usuarios"
    )
    conn.commit()
    conn.close()
    assert c.get("/extracao").status_code == 403


def test_usuario_desativado_perde_o_acesso(banco_exemplo):
    c = cliente_para(banco_exemplo)
    conn = sqlite3.connect(banco_exemplo)
    conn.execute("UPDATE usuarios SET ativo = 0")
    conn.commit()
    conn.close()
    assert c.get("/despesas").status_code == 302


def test_sair_encerra_a_sessao(banco_exemplo):
    c = cliente_para(banco_exemplo)
    c.post("/sair")
    assert c.get("/despesas").status_code == 302


# ---- 8. troca de senha obrigatória ----------------------------------------------------------


def test_primeiro_acesso_exige_trocar_a_senha(banco_exemplo):
    c = cliente_para(banco_exemplo, logado=False)
    with c.application.app_context():
        u = criar_usuario(login="novo", trocar=True)
    entrar(c, u)
    assert c.get("/despesas").headers["Location"].endswith("/trocar-senha")
    assert (
        c.post(
            "/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False}
        ).status_code
        == 403
    )
    r = c.post(
        "/trocar-senha",
        data={"atual": SENHA_TESTE, "nova": "OutraSenha456", "repetida": "OutraSenha456"},
    )
    assert r.status_code == 302
    assert c.get("/despesas").status_code == 200


@pytest.mark.parametrize(
    "atual, nova, repetida",
    [
        ("Errada123456", "OutraSenha456", "OutraSenha456"),  # atual errada
        (SENHA_TESTE, "curta1", "curta1"),  # política
        (SENHA_TESTE, "SemNumeroAqui", "SemNumeroAqui"),
        (SENHA_TESTE, "OutraSenha456", "Diferente456"),  # não confere
        (SENHA_TESTE, SENHA_TESTE, SENHA_TESTE),  # igual à atual
    ],
)
def test_troca_de_senha_recusa_o_que_nao_presta(banco_exemplo, atual, nova, repetida):
    c = cliente_para(banco_exemplo)
    r = c.post("/trocar-senha", data={"atual": atual, "nova": nova, "repetida": repetida})
    assert r.status_code == 400


# ---- 9. usuários (Admin) --------------------------------------------------------------------


@pytest.fixture
def empresas_fixas(monkeypatch):
    """A lista de empresas vem do .env da máquina; o teste fixa a sua (o CI não tem .env)."""
    from financeiro.config.companies import CompanyConfig
    import financeiro.web.admin as tela

    fixas = [CompanyConfig(k, k, "t" * 40, None, None) for k in ("ALFA", "BETA")]
    monkeypatch.setattr(tela, "load_companies", lambda: fixas)


def _usuario(caminho, login):
    conn = sqlite3.connect(caminho)
    linha = conn.execute(
        "SELECT perfil, deve_trocar_senha FROM usuarios WHERE login = ?", (login,)
    ).fetchone()
    conn.close()
    return linha


def test_admin_cria_usuario_com_senha_provisoria_e_troca_obrigatoria(banco_exemplo, empresas_fixas):
    c = cliente_para(banco_exemplo)
    r = c.post(
        "/admin/usuarios/novo",
        data={"login": "fulano", "nome": "Fulano", "perfil": "financeiro", "empresas": ["ALFA"]},
    )
    assert r.status_code == 200 and "senha-provisoria" in r.get_data(as_text=True)
    assert _usuario(banco_exemplo, "fulano") == ("financeiro", 1)


@pytest.mark.parametrize(
    "dados",
    [
        {"login": "x", "nome": "N", "perfil": "financeiro", "empresas": ["ALFA"]},  # login curto
        {
            "login": "sicrano",
            "nome": "N",
            "perfil": "root",
            "empresas": ["ALFA"],
        },  # perfil inventado
        {
            "login": "sicrano",
            "nome": "N",
            "perfil": "financeiro",
            "empresas": ["GAMA"],
        },  # empresa inventada
        {"login": "sicrano", "nome": "N", "perfil": "leitura", "empresas": []},  # sem empresa
    ],
)
def test_admin_nao_cria_usuario_invalido(banco_exemplo, empresas_fixas, dados):
    c = cliente_para(banco_exemplo)
    assert c.post("/admin/usuarios/novo", data=dados).status_code == 400
    assert _usuario(banco_exemplo, dados["login"]) is None


def test_admin_nao_rebaixa_a_si_mesmo(banco_exemplo):
    c = cliente_para(banco_exemplo)
    conn = sqlite3.connect(banco_exemplo)
    (uid,) = conn.execute("SELECT id FROM usuarios WHERE login = 'teste-admin-todas'").fetchone()
    conn.close()
    r = c.post(
        f"/admin/usuarios/{uid}",
        data={"nome": "Eu", "perfil": "leitura", "empresas": [], "ativo": "1"},
    )
    assert r.status_code == 400
    assert c.get("/extracao").status_code == 200  # continua Admin


# ---- 10. escopo no repositório e SQL com nome de coluna -------------------------------------


def test_repositorio_erra_sem_escopo(banco_exemplo):
    from financeiro.receitas import listar_notas
    from financeiro.repositorio_contas_pagar import listar_contas, listar_valores_distintos

    for chamada in (
        lambda: listar_contas(None),
        lambda: listar_notas(None),
        lambda: listar_valores_distintos(None, "empresa"),
    ):
        with pytest.raises(esc.ErroEscopo):
            chamada()


def test_escopo_sem_empresa_nao_ve_nada(banco_exemplo):
    from financeiro.repositorio_contas_pagar import listar_contas

    vazio = Escopo(usuario_id=1, login="x", perfil="financeiro", empresas=frozenset())
    assert listar_contas(vazio) == []
    assert len(listar_contas(SISTEMA)) == 11


@pytest.mark.parametrize("coluna", ["empresa; DROP TABLE notas", "historico", "1=1 OR empresa"])
def test_nome_de_coluna_fora_da_lista_branca_e_recusado(banco_exemplo, coluna):
    from financeiro.repositorio_contas_pagar import listar_contas, listar_valores_distintos

    with pytest.raises(ValueError):
        listar_valores_distintos(SISTEMA, coluna)
    with pytest.raises(ValueError):
        listar_contas(SISTEMA, {coluna: ["x"]})


def test_clausula_recusa_identificador_invalido():
    with pytest.raises(esc.ErroEscopo):
        esc.clausula(SISTEMA, "empresa) OR (1=1")


def test_escopo_so_aceita_perfil_conhecido():
    with pytest.raises(esc.ErroEscopo):
        Escopo(usuario_id=1, login="x", perfil="superusuario")


# ---- 11. LGPD ---------------------------------------------------------------------------------


def test_listagem_de_notas_nao_le_cpf(banco_exemplo):
    from financeiro.receitas import listar_notas

    assert all("cliente_cpf_cnpj" not in n for n in listar_notas(SISTEMA))


@pytest.mark.parametrize(
    "doc, esperado",
    [
        ("123.456.789-09", "***.456.789-**"),
        ("12345678909", "***.456.789-**"),
        ("12.345.678/0001-90", "12.345.678/0001-90"),
        (None, ""),
    ],
)
def test_cpf_mascarado(doc, esperado):
    from financeiro.validacao import mascarar_documento

    assert mascarar_documento(doc) == esperado


# ---- 12. validação de entrada -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rota, corpo",
    [
        ("/despesas/marcar", {"empresa": "ALFA", "id": "abc", "considerar": False}),
        ("/despesas/marcar", {"empresa": "ALFA", "id": "1", "considerar": "sim"}),
        ("/despesas/marcar", {"empresa": "", "id": "1", "considerar": True}),
        (
            "/receitas/marcar",
            {"empresa": "ALFA", "tipo_nota": "xpto", "id": "101", "considerar": True},
        ),
        (
            "/receitas/ajustar",
            {"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "13/2026"},
        ),
        (
            "/receitas/ajustar",
            {"empresa": "BETA", "tipo_nota": "servico", "id": "204", "categoria": "x" * 200},
        ),
        ("/extracao/iniciar", {"empresa": "TODAS", "ano": 1990}),
        ("/extracao/iniciar", {"empresa": "EMPRESA_X", "ano": 2026}),
    ],
)
def test_entrada_invalida_da_400(banco_exemplo, rota, corpo):
    c = cliente_para(banco_exemplo)
    assert c.post(rota, json=corpo).status_code == 400


def test_corpo_que_nao_e_json_nao_derruba(banco_exemplo):
    c = cliente_para(banco_exemplo)
    r = c.post("/despesas/marcar", data="lixo", content_type="text/plain")
    assert r.status_code == 400
