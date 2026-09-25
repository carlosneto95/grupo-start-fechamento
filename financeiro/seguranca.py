"""Login, sessão, permissões e headers de segurança.

Padrão do Controle de Impostos (sistema/seguranca.py), adaptado:
  1. senha com hash scrypt (werkzeug) e bloqueio de 15 min após 5 erros;
  2. o cookie guarda SÓ o id do usuário, a versão da sessão e o instante da
     última ação, assinados com a GSF_SECRET_KEY. Perfil e empresas são
     RELIDOS DO BANCO a cada requisição e viram `g.escopo`;
  3. a sessão expira após 60 minutos parada;
  4. primeiro acesso (ou senha redefinida pelo Admin) obriga a trocar a senha;
  5. decoradores de rota por perfil;
  6. headers de segurança em toda resposta.

Esconder um botão NÃO é segurança. A trava de verdade é esta, no servidor,
antes de a rota rodar.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from financeiro import usuarios
from financeiro.db import agora_brasilia

MAX_TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15
MINUTOS_INATIVIDADE = 60

# Rotas que funcionam sem login.
ROTAS_PUBLICAS = {"auth.login", "static"}
# Rotas liberadas enquanto a troca de senha obrigatória não é feita.
ROTAS_DA_TROCA = {"auth.trocar_senha", "auth.sair", "static"}

# Hash usado quando o login não existe: a conferência leva o mesmo tempo que a
# de um usuário real, e medir a demora não revela quais logins existem.
_HASH_FALSO = generate_password_hash("senha-inexistente-para-igualar-o-tempo")

MENSAGEM_INVALIDO = "Usuário ou senha inválidos."
MENSAGEM_BLOQUEIO = "Acesso bloqueado temporariamente por excesso de tentativas. Tente mais tarde."


# ---- 1. login --------------------------------------------------------------------


def autenticar(login: str, senha: str):
    """(usuario, None) no acerto; (None, mensagem) no erro. A mensagem é a
    mesma para login inexistente e senha errada."""
    login = (login or "").strip().lower()[:40]
    usuario = usuarios._por_login(login) if login else None

    if usuario is None or not usuario["ativo"]:
        check_password_hash(_HASH_FALSO, senha or "")  # iguala o tempo
        usuarios.registrar_evento(
            "login_falhou", login, detalhe={"motivo": "inexistente_ou_inativo"}
        )
        return None, MENSAGEM_INVALIDO

    agora = agora_brasilia()
    if usuario["bloqueado_ate"] and usuario["bloqueado_ate"] > agora:
        usuarios.registrar_evento("login_bloqueado", usuario["login"], usuario["id"])
        return None, MENSAGEM_BLOQUEIO

    if not check_password_hash(usuario["senha_hash"], senha or ""):
        tentativas = usuario["tentativas_falhas"] + 1
        if tentativas >= MAX_TENTATIVAS:
            ate = datetime.fromisoformat(agora) + timedelta(minutes=MINUTOS_BLOQUEIO)
            campos = {"tentativas_falhas": 0, "bloqueado_ate": ate.isoformat(timespec="seconds")}
            evento = "login_bloqueou"
        else:
            campos, evento = {"tentativas_falhas": tentativas}, "login_falhou"
        usuarios._atualizar_login(usuario["id"], campos, evento, usuario["login"])
        return None, (MENSAGEM_BLOQUEIO if tentativas >= MAX_TENTATIVAS else MENSAGEM_INVALIDO)

    usuarios._atualizar_login(
        usuario["id"],
        {"tentativas_falhas": 0, "bloqueado_ate": None, "ultimo_login": agora},
        "login",
        usuario["login"],
    )
    return usuario, None


def iniciar_sessao(usuario) -> None:
    """session.clear() antes: descarta sessão anterior (fixação de sessão)."""
    session.clear()
    session.permanent = True
    session["uid"] = usuario["id"]
    session["sv"] = usuario["sessao_versao"]
    session["ultimo"] = int(time.time())


def encerrar_sessao() -> None:
    session.clear()


# ---- 2, 3 e 4. a cada requisição: sessão -> escopo --------------------------------


def carregar_escopo():
    """before_request de TODA rota. Sem sessão válida, manda para o login;
    com ela, monta g.escopo do banco. Troca de senha pendente só libera a
    própria troca e o sair."""
    g.escopo = None
    g.usuario_nome = None
    if request.endpoint in ROTAS_PUBLICAS or request.endpoint is None:
        return None

    uid = session.get("uid")
    if not uid:
        return _para_login()
    if int(time.time()) - int(session.get("ultimo", 0)) > MINUTOS_INATIVIDADE * 60:
        encerrar_sessao()
        return _para_login(expirou=True)

    usuario = usuarios._por_id(uid)
    if usuario is None or not usuario["ativo"] or usuario["sessao_versao"] != session.get("sv"):
        encerrar_sessao()
        return _para_login()

    g.escopo = usuarios.escopo_de(usuario)
    g.usuario_nome = usuario["nome"]
    session["ultimo"] = int(time.time())  # renova a contagem de inatividade

    if usuario["deve_trocar_senha"] and request.endpoint not in ROTAS_DA_TROCA:
        if _quer_json():
            return {"ok": False, "erro": "troque a senha antes de continuar"}, 403
        return redirect(url_for("auth.trocar_senha"))
    return None


def _quer_json() -> bool:
    return request.is_json or request.path.startswith(("/api/",)) or request.method != "GET"


def _para_login(expirou: bool = False):
    # Chamada de API/POST sem sessão: 401 em JSON, não um redirect que o fetch
    # seguiria e leria como HTML.
    if _quer_json():
        return {"ok": False, "erro": "sessão expirada — entre de novo"}, 401
    return redirect(
        url_for(
            "auth.login",
            proximo=destino_seguro(request.full_path, ""),
            expirou=1 if expirou else None,
        )
    )


def destino_seguro(destino: str | None, padrao: str = "/") -> str:
    """Só caminho interno ("/despesas"), nunca "https://site" nem "//site"
    (open redirect)."""
    destino = (destino or "").strip()
    if not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return padrao
    return destino.rstrip("?") or padrao


# ---- 5. decoradores de rota ------------------------------------------------------


def _negar():
    usuarios.registrar_evento(
        "acesso_negado", g.escopo.login if g.escopo else "", detalhe={"rota": request.path}
    )
    abort(403)


def admin_necessario(f):
    """Regras de exclusão, sincronização e usuários: só Admin. 403 (e não 404):
    a tela existe, só não é para este perfil."""

    @wraps(f)
    def envolvida(*args, **kwargs):
        if g.get("escopo") is None or not g.escopo.eh_admin:
            _negar()
        return f(*args, **kwargs)

    return envolvida


def escrita_necessaria(f):
    """Marcar e ajustar: Admin e Financeiro. O perfil Leitura recebe 403."""

    @wraps(f)
    def envolvida(*args, **kwargs):
        if g.get("escopo") is None or not g.escopo.pode_escrever:
            _negar()
        return f(*args, **kwargs)

    return envolvida


# ---- 6. headers --------------------------------------------------------------------

# Só scripts do próprio sistema (nenhum inline, nenhuma CDN). Estilo do próprio
# sistema + folha do Google Fonts; fontes do gstatic. Google Fonts é a única
# origem externa (Fase 3 usa Fraunces e IBM Plex).
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def aplicar_headers(resposta):
    h = resposta.headers
    h.setdefault("Content-Security-Policy", CSP)
    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    h["X-Frame-Options"] = "DENY"
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Página com resultado financeiro não fica no cache do navegador nem de proxy.
    if request.endpoint != "static":
        h["Cache-Control"] = "no-store"
    return resposta
