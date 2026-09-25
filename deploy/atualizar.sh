#!/bin/bash
# ===========================================================================
# atualizar.sh - PUBLICA UMA NOVA VERSAO SEM PERDER DADOS
#
#   bash ~/financeiro/deploy/atualizar.sh ~/financeiro_AAAAMMDD_HHMM.zip
#
# 1. descompacta a versao nova numa pasta TEMPORARIA
# 2. roda a suite de testes NELA (bancos temporarios) - falhou, para aqui
#    e NADA muda no sistema em producao
# 3. backup do banco (API do SQLite: copia consistente com o sistema no ar)
# 4. copia o codigo novo por cima: data/, backups/, logs/, relatorios/,
#    .env e tests/golden/esperado/ NUNCA sao tocados
# 5. aplica migracoes (com backup automatico) e recarrega o web app
# ===========================================================================
set -e

# O script roda a partir de uma COPIA em /tmp: ele substitui a propria pasta
# deploy/, e no disco de rede do PythonAnywhere um arquivo aberto impede apagar
# a pasta ("Directory not empty") - licao do deploy do Impostos.
if [ -z "$FINANCEIRO_ATUALIZAR_COPIA" ]; then
    COPIA_SCRIPT=$(mktemp)
    cp "$0" "$COPIA_SCRIPT"
    FINANCEIRO_ATUALIZAR_COPIA=1 exec bash "$COPIA_SCRIPT" "$@"
fi

ZIP="$1"
PROJETO=${FINANCEIRO_PROJETO:-$HOME/financeiro}

# Configuracao da conta (fora do git, criada uma vez - ver o passo a passo
# privado): FINANCEIRO_VENV (virtualenv compartilhado) e FINANCEIRO_OUTROS
# (caminhos dos outros sistemas, conferidos antes e depois de anexar o WSGI).
[ -f "$PROJETO/.deploy.env" ] && . "$PROJETO/.deploy.env"
: "${FINANCEIRO_VENV:?defina FINANCEIRO_VENV em $PROJETO/.deploy.env}"
VENV=$FINANCEIRO_VENV
PY="$VENV/bin/python"
WSGI=${FINANCEIRO_WSGI:-/var/www/$(whoami)_pythonanywhere_com_wsgi.py}
ITENS="financeiro templates static scripts deploy app.py pyproject.toml requirements.txt README.md HISTORICO.md DEPLOY.md .env.example"

[ -f "$ZIP" ] || { echo "Uso: bash atualizar.sh financeiro_AAAAMMDD_HHMM.zip"; exit 1; }

NOVO=$(mktemp -d)
trap 'rm -rf "$NOVO"' EXIT
echo ">>> 1/5 Descompactando em $NOVO"
unzip -q "$ZIP" -d "$NOVO"
[ -f "$NOVO/financeiro/__init__.py" ] || { echo "ERRO: o zip nao tem a pasta financeiro/"; exit 1; }

echo ">>> 2/5 Testes na versao nova"
# O golden precisa da copia congelada: a da producao e emprestada (so leitura).
if [ -d "$PROJETO/tests/golden/esperado" ]; then
    mkdir -p "$NOVO/tests/golden"
    cp -r "$PROJETO/tests/golden/esperado" "$NOVO/tests/golden/"
fi
if ! bash "$NOVO/deploy/testar.sh" "$NOVO"; then
    echo "ERRO: testes falharam. NADA foi alterado no sistema em producao."
    exit 1
fi

echo ">>> 3/5 Backup do banco"
"$PY" - "$PROJETO" <<'EOF'
import datetime, os, sqlite3, sys
raiz = sys.argv[1]
banco = os.path.join(raiz, "data", "app.db")
if os.path.exists(banco):
    destino = os.path.join(raiz, "backups",
                           "antes_atualizacao_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
    origem, copia = sqlite3.connect(banco), sqlite3.connect(destino)
    origem.backup(copia)
    copia.close(); origem.close()
    os.chmod(destino, 0o600)
    print("    backup:", destino)
EOF

echo ">>> 4/5 Copiando o codigo novo"
for item in $ITENS tests; do
    if [ -e "$NOVO/$item" ]; then
        if [ "$item" = "tests" ]; then
            # tests/ troca inteira, MENOS a copia congelada do golden.
            find "$PROJETO/tests" -mindepth 1 -maxdepth 1 ! -name golden -exec rm -rf {} + 2>/dev/null || true
            find "$PROJETO/tests/golden" -mindepth 1 -maxdepth 1 ! -name esperado -exec rm -rf {} + 2>/dev/null || true
            (cd "$NOVO" && find tests -path tests/golden/esperado -prune -o -type f -print) | while read -r f; do
                mkdir -p "$PROJETO/$(dirname "$f")"
                cp "$NOVO/$f" "$PROJETO/$f"
            done
            continue
        fi
        rm -rf "$PROJETO/$item.velho"
        [ -e "$PROJETO/$item" ] && mv "$PROJETO/$item" "$PROJETO/$item.velho"
        cp -r "$NOVO/$item" "$PROJETO/$item"
        rm -rf "$PROJETO/$item.velho" 2>/dev/null || true
    fi
done

echo ">>> 5/5 Migracoes e recarga"
cd "$PROJETO"
"$PY" -c "from financeiro import criar_app; criar_app(); print('    banco atualizado')"
touch "$WSGI"
echo "Pronto: nova versao no ar."
