"""Fábrica do aplicativo: `criar_app()`.

Aqui ficam só as ligações — configuração do .env, banco, log, rotas,
filtros de template e páginas de erro. Padrão do Controle de Impostos
(sistema/__init__.py). O `app.py` da raiz só chama esta função.
"""

from __future__ import annotations

import logging

from flask import Flask, g, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import HTTPException

from app import configuracao, db, pendencias, registro, seguranca

csrf = CSRFProtect()

log = logging.getLogger("app")


def criar_app(sobrescrever: dict | None = None) -> Flask:
    """Monta o app. `sobrescrever` troca itens da configuração (os testes
    passam banco e chave próprios em vez de ler o .env da máquina)."""
    # template_folder/static_folder apontam para a raiz: as pastas continuam
    # onde sempre estiveram, fora do pacote.
    app = Flask(
        __name__,
        template_folder=str(configuracao.RAIZ / "templates"),
        static_folder=str(configuracao.RAIZ / "static"),
    )
    app.config.update(configuracao.config_flask(sobrescrever))
    registro.configurar(app.config["PASTA_LOGS"])

    # Autoescape do Jinja fica LIGADO (padrão para .html). Reforço explícito:
    # nenhum dado vindo do Tiny pode virar HTML.
    app.jinja_env.autoescape = True
    # Tira do HTML a linha e a indentação que sobram das tags {% %}: na tela
    # de Despesas (15 mil linhas) era boa parte dos 13 MB enviados ao navegador.
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    # O banco é um só por processo. Scripts e a thread de sincronização usam
    # app.db sem contexto de requisição, então o caminho fica no módulo.
    # Migrações pendentes são aplicadas aqui, com backup verificado antes.
    db.configurar(app.config["CAMINHO_BANCO"], app.config["PASTA_BACKUPS"])
    db.migrar()

    # CSRF em todo POST, inclusive os fetch JSON (token no cabeçalho X-CSRFToken).
    csrf.init_app(app)
    # A cada requisição: sessão -> escopo (perfil e empresas lidos do banco).
    app.before_request(seguranca.carregar_escopo)
    app.after_request(seguranca.aplicar_headers)

    _registrar_filtros(app)
    _registrar_erros(app)

    @app.context_processor
    def _contexto():
        # O template esconde o que o perfil não pode fazer. Esconder é só
        # conforto: a trava é o decorador na rota (app/seguranca.py).
        escopo = g.get("escopo")
        return {
            "escopo": escopo,
            "usuario_nome": g.get("usuario_nome"),
            "pode_escrever": bool(escopo and escopo.pode_escrever),
            "eh_admin": bool(escopo and escopo.eh_admin),
            # Selo "sincronizado há N dias" (Fase 4.1): consulta barata ao
            # histórico de sincronização; fica vermelho acima de 2 dias.
            "selo_sincronizacao": pendencias.selo(escopo) if escopo else None,
        }

    from app import web

    web.registrar(app)
    return app


def _registrar_filtros(app: Flask) -> None:
    from app.visao import formatar_valor

    app.jinja_env.filters["moeda"] = formatar_valor
    # Diferença com sinal explícito (+1.234,50 / -80,00): efeito pós-fechamento.
    app.jinja_env.filters["moeda_sinal"] = lambda v: (
        ("+" if (v or 0) > 0 else "") + formatar_valor(v)
    )


def _registrar_erros(app: Flask) -> None:
    """Tela genérica para o usuário; detalhe completo só no log."""

    def pagina(codigo: int, titulo: str, texto: str):
        return render_template("erro.html", codigo=codigo, titulo=titulo, texto=texto), codigo

    @app.errorhandler(404)
    def _404(_e):
        return pagina(404, "Página não encontrada", "O endereço não existe.")

    @app.errorhandler(403)
    def _403(_e):
        if request.is_json or request.method != "GET":
            return {"ok": False, "erro": "sem permissão"}, 403
        return pagina(403, "Acesso não autorizado", "Esta ação não é permitida para o seu perfil.")

    @app.errorhandler(CSRFError)
    def _csrf(_e):
        if request.is_json or request.path.startswith("/api/"):
            return {"ok": False, "erro": "formulário expirado — recarregue a página"}, 400
        return pagina(400, "Formulário expirado", "Recarregue a página e tente de novo.")

    @app.errorhandler(Exception)
    def _erro(e):
        if isinstance(e, HTTPException):
            return pagina(e.code or 500, "Erro", "Não foi possível concluir a solicitação.")
        log.exception("Erro não tratado")
        return pagina(500, "Erro interno", "Algo deu errado. O erro foi registrado; tente de novo.")
