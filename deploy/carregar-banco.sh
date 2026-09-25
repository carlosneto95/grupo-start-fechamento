#!/bin/bash
# ===========================================================================
# carregar-banco.sh - CARGA INICIAL DO BANCO (uma unica vez)
#
#   bash ~/financeiro/deploy/carregar-banco.sh ~/financeiro_carga_AAAAMMDD_HHMM.zip
#
# 1. RECUSA se ja existir data/app.db: depois da carga o servidor e a fonte
#    da verdade, e sobrescrever apagaria o que foi feito aqui
# 2. descompacta numa pasta temporaria e confere o SHA-256 do banco
# 3. instala o banco (permissao 600) e o golden (tests/golden/esperado/)
# 4. aplica as migracoes pendentes (com backup automatico) e confere os
#    numeros contra o manifesto: contagens, somas e ajustes manuais
# 5. roda a suite de testes (deploy/testar.sh), golden incluido
# ===========================================================================
set -e

ZIP="$1"
PROJETO=${FINANCEIRO_PROJETO:-$HOME/financeiro}

# Configuracao da conta (fora do git, criada uma vez - ver o passo a passo
# privado): FINANCEIRO_VENV (virtualenv compartilhado) e FINANCEIRO_OUTROS
# (caminhos dos outros sistemas, conferidos antes e depois de anexar o WSGI).
[ -f "$PROJETO/.deploy.env" ] && . "$PROJETO/.deploy.env"
: "${FINANCEIRO_VENV:?defina FINANCEIRO_VENV em $PROJETO/.deploy.env}"
VENV=$FINANCEIRO_VENV
PY="$VENV/bin/python"
cd "$PROJETO"

[ -f "$ZIP" ] || { echo "Uso: bash carregar-banco.sh financeiro_carga_AAAAMMDD_HHMM.zip"; exit 1; }
if [ -e data/app.db ]; then
    echo "ERRO: data/app.db ja existe. A carga inicial so roda uma vez: o banco do"
    echo "servidor e a fonte da verdade. Para refazer de proposito, mova o banco atual"
    echo "para backups/ a mao (mv data/app.db backups/app_substituido.db) e rode de novo."
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo ">>> 1/4 Descompactando e conferindo o arquivo"
unzip -q "$ZIP" -d "$TMP"
[ -f "$TMP/data/app.db" ] && [ -f "$TMP/manifesto.json" ] || { echo "ERRO: pacote de carga incompleto"; exit 1; }
"$PY" deploy/conferir_carga.py "$TMP/data/app.db" "$TMP/manifesto.json" --hash

echo ">>> 2/4 Instalando banco e golden"
mkdir -p data backups tests/golden/esperado
cp "$TMP/data/app.db" data/app.db
chmod 600 data/app.db
cp "$TMP/manifesto.json" backups/manifesto_carga_inicial.json
if [ -d "$TMP/tests/golden/esperado" ]; then
    cp "$TMP/tests/golden/esperado/"* tests/golden/esperado/
    chmod 600 tests/golden/esperado/*
fi

echo ">>> 3/4 Migracoes e conferencia dos numeros"
"$PY" -c "from financeiro import criar_app; criar_app(); print('    migracoes aplicadas')"
"$PY" deploy/conferir_carga.py data/app.db backups/manifesto_carga_inicial.json

echo ">>> 4/4 Testes"
bash deploy/testar.sh

echo ""
echo "Carga concluida. A partir de agora o SERVIDOR e a fonte da verdade."
echo "Apague o zip de carga (tem dado real):  rm $ZIP"
echo "Proximo passo: bash $PROJETO/deploy/anexar-wsgi.sh"
