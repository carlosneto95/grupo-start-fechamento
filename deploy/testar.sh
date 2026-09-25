#!/bin/bash
# ===========================================================================
# testar.sh - RODA A SUITE DE TESTES NO SERVIDOR
#
#   bash ~/financeiro/deploy/testar.sh [pasta_do_projeto]
#
# O pytest NAO e instalado no virtualenv compartilhado: vai para uma pasta
# propria (.ferramentas-teste/, com --target) e entra so neste processo pelo
# PYTHONPATH. Assim nenhum pacote dos outros sistemas muda de versao.
#
# Os testes usam bancos temporarios; o golden compara com a copia congelada
# em tests/golden/esperado/ (se existir) - prova que as bibliotecas do venv
# compartilhado dao os mesmos numeros que as do computador.
# ===========================================================================
set -e

PROJETO=${1:-${FINANCEIRO_PROJETO:-$HOME/financeiro}}
FERRAMENTAS=${FINANCEIRO_FERRAMENTAS:-$HOME/financeiro/.ferramentas-teste}
CONF="${FINANCEIRO_PROJETO:-$HOME/financeiro}/.deploy.env"
[ -f "$CONF" ] && . "$CONF"
: "${FINANCEIRO_VENV:?defina FINANCEIRO_VENV em $CONF}"
VENV=$FINANCEIRO_VENV
PY="$VENV/bin/python"

if ! PYTHONPATH="$FERRAMENTAS" "$PY" -c "import pytest" 2>/dev/null; then
    echo "    instalando pytest em $FERRAMENTAS (fora do venv compartilhado)"
    "$VENV/bin/pip" install --quiet --target "$FERRAMENTAS" "pytest==9.1.1"
fi

cd "$PROJETO"
# -p no:cacheprovider: nada de .pytest_cache na pasta do projeto.
PYTHONPATH="$FERRAMENTAS" "$PY" -m pytest -q -p no:cacheprovider
