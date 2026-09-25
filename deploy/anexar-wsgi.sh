#!/bin/bash
# ===========================================================================
# anexar-wsgi.sh - LIGA O SISTEMA EM /financeiro, SEM MEXER NOS OUTROS
#
#   bash ~/financeiro/deploy/anexar-wsgi.sh
#
# 1. anota como os outros sistemas (FINANCEIRO_OUTROS) respondem AGORA
# 2. copia o WSGI atual para <arquivo>.backup-DATA (sempre da para voltar)
# 3. ACRESCENTA o bloco no fim do arquivo - nenhuma linha existente muda
# 4. confere a sintaxe; se quebrar, RESTAURA a copia
# 5. recarrega o web app e confere que os outros respondem COMO ANTES e que
#    /financeiro responde. Se algum dos outros mudou, RESTAURA a copia.
#
# Pode rodar de novo: se o bloco ja estiver la, avisa e sai sem duplicar.
# ===========================================================================
set -e

USUARIO=$(whoami)
PROJETO=${FINANCEIRO_PROJETO:-$HOME/financeiro}
WSGI=${FINANCEIRO_WSGI:-/var/www/${USUARIO}_pythonanywhere_com_wsgi.py}
BLOCO="$PROJETO/deploy/bloco_wsgi_financeiro.py"
PYTHON=${FINANCEIRO_PYTHON:-python3}
SITE=${FINANCEIRO_SITE:-https://${USUARIO}.pythonanywhere.com}
[ -f "$PROJETO/.deploy.env" ] && . "$PROJETO/.deploy.env"
OUTROS=${FINANCEIRO_OUTROS:?defina FINANCEIRO_OUTROS em $PROJETO/.deploy.env}

[ -f "$WSGI" ]  || { echo "ERRO: WSGI nao encontrado em $WSGI"; exit 1; }
[ -f "$BLOCO" ] || { echo "ERRO: bloco nao encontrado em $BLOCO"; exit 1; }

if grep -q "FINANCEIRO_INICIO" "$WSGI"; then
    echo "O bloco do Financeiro JA ESTA no WSGI. Nada a fazer."
    exit 0
fi

# Codigo HTTP de cada sistema (sem seguir redirecionamento: 302 para o login
# conta como "no ar", e e isso que tem de continuar igual).
situacao () {
    for caminho in $OUTROS; do
        # || true: timeout ou conexao recusada vira "000", nao encerra o script (set -e).
        printf '%s=%s ' "$caminho" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$SITE$caminho" || true)"
    done
}
ANTES=$(situacao)
echo ">>> Antes:  $ANTES"

COPIA="${WSGI}.backup-$(date +%Y%m%d-%H%M%S)"
cp "$WSGI" "$COPIA"
echo ">>> Copia de seguranca: $COPIA"

printf '\n\n' >> "$WSGI"
# O bloco versionado nao tem caminho de conta: ele entra aqui.
sed "s#__CAMINHO_DO_PROJETO__#$PROJETO#" "$BLOCO" >> "$WSGI"
echo ">>> Bloco anexado no fim do arquivo."

if ! "$PYTHON" -m py_compile "$WSGI"; then
    cp "$COPIA" "$WSGI"
    echo "ERRO de sintaxe: o arquivo original foi RESTAURADO. Nada mudou."
    exit 1
fi
echo ">>> Sintaxe conferida."

touch "$WSGI"
echo ">>> Recarregando (aguardando o web app subir)..."
sleep 20
DEPOIS=$(situacao)
echo ">>> Depois: $DEPOIS"
NOSSO=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$SITE/financeiro/login" || true)

if [ "$ANTES" != "$DEPOIS" ]; then
    cp "$COPIA" "$WSGI"
    touch "$WSGI"
    echo "ERRO: outro sistema passou a responder diferente. WSGI RESTAURADO e recarregado."
    echo "Veja o Error log da aba Web antes de tentar de novo."
    exit 1
fi
if [ "$NOSSO" != "200" ]; then
    echo "ATENCAO: /financeiro/login respondeu $NOSSO (os outros seguem iguais)."
    echo "Veja o Error log da aba Web. Para desligar: cp $COPIA $WSGI && touch $WSGI"
    exit 1
fi
echo ">>> /financeiro/login respondeu 200. Abra $SITE/financeiro/"
