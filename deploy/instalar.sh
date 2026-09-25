#!/bin/bash
# ===========================================================================
# instalar.sh - PRIMEIRA INSTALACAO NO PYTHONANYWHERE (pode rodar de novo)
#
#   bash ~/financeiro/deploy/instalar.sh
#
# 1. confere o Python do virtualenv compartilhado (3.11 ou mais)
# 2. pastas data/, backups/, logs/, relatorios/ so do dono
# 3. .env com GSF_SECRET_KEY NOVA (gerada aqui, nunca exibida); os tokens do
#    Tiny voce preenche depois, direto no arquivo
# 4. bibliotecas: instala SO as que faltam no virtualenv compartilhado
#    (nunca atualiza as que existem - os outros sistemas da conta usam o
#    mesmo venv); "pip check" antes e depois
#
# NAO cria o banco: ele chega pela carga inicial (carregar-banco.sh).
# ===========================================================================
set -e

PROJETO=${FINANCEIRO_PROJETO:-$HOME/financeiro}

# Configuracao da conta (fora do git, criada uma vez - ver o passo a passo
# privado): FINANCEIRO_VENV (virtualenv compartilhado) e FINANCEIRO_OUTROS
# (caminhos dos outros sistemas, conferidos antes e depois de anexar o WSGI).
[ -f "$PROJETO/.deploy.env" ] && . "$PROJETO/.deploy.env"
: "${FINANCEIRO_VENV:?defina FINANCEIRO_VENV em $PROJETO/.deploy.env}"
VENV=$FINANCEIRO_VENV
PY="$VENV/bin/python"
cd "$PROJETO"

echo ">>> 1/4 Python do virtualenv compartilhado"
"$PY" -c "import sys; assert sys.version_info >= (3, 11), sys.version; print('    ok:', sys.version.split()[0])" \
    || { echo "ERRO: o sistema precisa de Python 3.11+. Nada foi instalado."; exit 1; }

echo ">>> 2/4 Pastas"
mkdir -p data backups logs relatorios
chmod 700 data backups logs relatorios

echo ">>> 3/4 Arquivo .env"
if [ ! -f .env ]; then
    CHAVE=$("$PY" -c "import secrets; print(secrets.token_urlsafe(48))")
    {
        echo "GSF_SECRET_KEY=$CHAVE"
        echo "GSF_PREFIXO=/financeiro"
        echo "GSF_BANCO=$PROJETO/data/app.db"
        echo "GSF_LOGS=$PROJETO/logs"
        echo "GSF_BACKUPS=$PROJETO/backups"
        echo "GSF_COOKIE_SEGURO=1"
        echo "GSF_AMBIENTE=production"
        echo ""
        echo "# Tokens do Tiny (API v2), um por empresa. Preencha pela aba Files."
        echo "GSF_EMPRESA1_NOME=MSV"
        echo "GSF_EMPRESA1_TINY_API_TOKEN="
        echo "GSF_EMPRESA2_NOME=START"
        echo "GSF_EMPRESA2_TINY_API_TOKEN="
        echo "GSF_EMPRESA3_NOME=GTF"
        echo "GSF_EMPRESA3_TINY_API_TOKEN="
    } > .env
    unset CHAVE
    echo "    .env criado com chave nova. Faltam os tokens do Tiny (aba Files)."
else
    echo "    .env ja existe: mantido."
fi
chmod 600 .env

echo ">>> 4/4 Bibliotecas (so as que faltam)"
echo "    pip check ANTES:"
"$VENV/bin/pip" check 2>&1 | sed 's/^/      /' || true
instalar_se_faltar () {   # $1 = modulo para importar; $2... = pacotes pip
    local modulo="$1"; shift
    if "$PY" -c "import $modulo" 2>/dev/null; then
        # Versao pelo nome do pacote pip (o texto antes de >=, <, ==).
        echo "    ok: $modulo $("$PY" -c "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))" "${1%%[<>=]*}" 2>/dev/null) (ja instalado, nao mexo)"
    else
        echo "    instalando $*"
        "$VENV/bin/pip" install --quiet "$@"
    fi
}
instalar_se_faltar flask "Flask>=3.1,<4"
instalar_se_faltar flask_wtf "Flask-WTF>=1.2,<2"
instalar_se_faltar dotenv "python-dotenv>=1.0"
instalar_se_faltar openpyxl "openpyxl>=3.1"
instalar_se_faltar requests "requests>=2.31,<3"
echo "    pip check DEPOIS:"
"$VENV/bin/pip" check 2>&1 | sed 's/^/      /' || true

echo ""
echo "Proximo passo: bash $PROJETO/deploy/carregar-banco.sh ~/financeiro_carga_AAAAMMDD_HHMM.zip"
