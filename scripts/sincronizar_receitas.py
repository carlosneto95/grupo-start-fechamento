"""
Traz as notas fiscais emitidas (receita) do Tiny para o banco.

Uso:
    python scripts/sincronizar_receitas.py MSV                     # ano atual
    python scripts/sincronizar_receitas.py MSV --desde 2025-01-01
    python scripts/sincronizar_receitas.py TODAS --desde 2025-01-01 --ate 2026-12-31
"""
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config.companies import load_companies
from app.db import init_db
from app.receitas import sincronizar_notas
from app.tiny_client.api_client import TinyAPIClient, TinyAPIError


def opcao(nome: str, padrao=None):
    marca = f"--{nome}"
    if marca in sys.argv:
        i = sys.argv.index(marca)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return padrao


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    todas = load_companies()
    if not todas:
        print("Nenhuma empresa configurada no .env.")
        return

    disponiveis = ", ".join(e.nome for e in todas)
    if not argumentos:
        print(f"Informe a empresa. Configuradas: {disponiveis} (ou TODAS)")
        return

    alvo = argumentos[0]
    empresas = todas if alvo.upper() == "TODAS" else [
        e for e in todas if alvo.upper() in (e.nome.upper(), e.key.upper())
    ]
    if not empresas:
        print(f"Empresa '{alvo}' não encontrada. Configuradas: {disponiveis}")
        return

    hoje = date.today()
    desde = opcao("desde")
    ate = opcao("ate")
    data_ini = date.fromisoformat(desde) if desde else date(hoje.year, 1, 1)
    data_fim = date.fromisoformat(ate) if ate else date(hoje.year, 12, 31)

    init_db()
    print(f"Notas emitidas de {data_ini} a {data_fim}\n")

    for empresa in empresas:
        print(f"=== {empresa.nome} ===")
        if not empresa.has_api_token:
            print("  sem token no .env — pulando.\n")
            continue

        cliente = TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)
        ultimo = {"marco": -1}

        def progresso(feitos, total, etapa, ultimo=ultimo):
            if total and feitos:
                pct = int(100 * feitos / total)
                if pct // 10 != ultimo["marco"]:
                    ultimo["marco"] = pct // 10
                    print(f"  [{datetime.now():%H:%M:%S}] {feitos}/{total} ({pct}%) — {etapa}")

        try:
            r = sincronizar_notas(cliente, empresa.nome, data_ini, data_fim, progresso)
        except TinyAPIError as e:
            print(f"  ERRO: {e}\n")
            continue

        print(f"  notas: {r['encontradas']} ({r['vendas']} venda, {r['servicos']} serviço)")
        print(f"  novas: {r['novas']} | já existiam: {r['atualizadas']}")
        print(f"  receita da empresa no banco: R$ {r['receita_total_empresa']:,.2f}\n")


if __name__ == "__main__":
    main()
