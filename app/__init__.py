"""Fábrica do aplicativo: `criar_app()`.

Aqui ficam só as ligações — configuração do .env, banco, log, rotas,
filtros de template e páginas de erro. Padrão do Controle de Impostos
(sistema/__init__.py). O `app.py` da raiz só chama esta função.
"""

from __future__ import annotations

import logging

from flask import Flask, render_template
from werkzeug.exceptions import HTTPException

from app import configuracao, db, registro

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

    # O banco é um só por processo. Scripts e a thread de sincronização usam
    # app.db sem contexto de requisição, então o caminho fica no módulo.
    # Migrações pendentes são aplicadas aqui, com backup verificado antes.
    db.configurar(app.config["CAMINHO_BANCO"], app.config["PASTA_BACKUPS"])
    db.migrar()

    _registrar_filtros(app)
    _registrar_erros(app)

    from app import web

    web.registrar(app)
    return app


def _registrar_filtros(app: Flask) -> None:
    from app.visao import formatar_valor

    app.jinja_env.filters["moeda"] = formatar_valor


def _registrar_erros(app: Flask) -> None:
    """Tela genérica para o usuário; detalhe completo só no log."""

    def pagina(codigo: int, titulo: str, texto: str):
        return render_template("erro.html", codigo=codigo, titulo=titulo, texto=texto), codigo

    @app.errorhandler(404)
    def _404(_e):
        return pagina(404, "Página não encontrada", "O endereço não existe.")

    @app.errorhandler(Exception)
    def _erro(e):
        if isinstance(e, HTTPException):
            return pagina(e.code or 500, "Erro", "Não foi possível concluir a solicitação.")
        log.exception("Erro não tratado")
        return pagina(500, "Erro interno", "Algo deu errado. O erro foi registrado; tente de novo.")
