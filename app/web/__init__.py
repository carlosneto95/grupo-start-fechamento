"""Rotas HTTP, uma área por blueprint.

Regra da casa: rota é FINA. Lê a requisição, chama `app.paineis` (leitura) ou
o repositório (escrita) e devolve template ou JSON. Nenhum cálculo de
fechamento mora aqui — está em app/paineis.py e nos módulos de domínio, onde
os testes alcançam sem subir servidor.
"""

from app.web import (
    admin,
    analise,
    api,
    auth,
    dashboard,
    despesas,
    dre,
    extracao,
    fechamento,
    pendencias,
    receitas,
)

BLUEPRINTS = (
    auth.bp,
    dashboard.bp,
    despesas.bp,
    receitas.bp,
    analise.bp,
    pendencias.bp,
    fechamento.bp,
    dre.bp,
    extracao.bp,
    admin.bp,
    api.bp,
)


def registrar(app) -> None:
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
