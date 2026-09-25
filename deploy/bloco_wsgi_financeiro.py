# ===========================================================================
# FINANCEIRO_INICIO  <- marcador: o anexar-wsgi.sh procura esta linha para
#                       saber se o bloco ja foi instalado. NAO apague.
#
# GRUPO START - FINANCEIRO (despesas, receitas, DRE, fechamento) em /financeiro
#
# COMO ESTE BLOCO FUNCIONA (e por que nao mexe nos outros sistemas):
# Ele NAO remonta a lista de sistemas. Pega o "application" que o arquivo ja
# definiu acima (o que serve os outros sistemas da conta) e o EMBRULHA:
#     - endereco que comeca com /financeiro -> vai para este sistema
#     - qualquer outro endereco             -> vai para o application
#                                              anterior, exatamente como antes
# Se este sistema falhar ao subir, o "application" anterior fica intacto e o
# motivo vai para o Error log da aba Web.
#
# NOMES DE MODULO: o pacote deste sistema chama "financeiro" de proposito.
# Ele se chamava "app", nome generico que outro sistema no mesmo processo
# tambem usa - e importa durante as requisicoes. Num processo so existe UM
# "app" em sys.modules: um dos dois acabaria usando o codigo do outro. Por
# isso este bloco so remove de sys.modules o que for "financeiro" - nunca
# modulos dos outros sistemas.
#
# O caminho abaixo e preenchido pelo anexar-wsgi.sh com a pasta do projeto.
# ===========================================================================

_FIN_CAMINHO = "__CAMINHO_DO_PROJETO__"
_fin_anterior = globals().get("application")

try:
    import sys as _fin_sys
    from werkzeug.middleware.dispatcher import DispatcherMiddleware as _FinDispatcher

    if _FIN_CAMINHO not in _fin_sys.path:
        _fin_sys.path.insert(0, _FIN_CAMINHO)

    for _fin_m in [
        m for m in list(_fin_sys.modules) if m == "financeiro" or m.startswith("financeiro.")
    ]:
        _fin_sys.modules.pop(_fin_m, None)

    # A configuracao (GSF_SECRET_KEY, GSF_PREFIXO, GSF_BANCO...) e lida do
    # .env do proprio projeto dentro de criar_app() - nao depende do que os
    # blocos acima puseram em os.environ (so nomes GSF_* sao aceitos).
    from financeiro import criar_app as _fin_criar_app

    _fin_app = _fin_criar_app()
    if _fin_anterior is not None:
        application = _FinDispatcher(_fin_anterior, {"/financeiro": _fin_app})

except Exception:
    import traceback as _fin_tb

    _fin_tb.print_exc()
    if _fin_anterior is not None:
        application = _fin_anterior

finally:
    # O pacote ja esta em sys.modules com o caminho absoluto; os imports
    # internos ("from financeiro import ...", inclusive os feitos durante as
    # requisicoes) continuam funcionando.
    try:
        _fin_sys.path.remove(_FIN_CAMINHO)
    except Exception:
        pass
# FINANCEIRO_FIM
# ===========================================================================
