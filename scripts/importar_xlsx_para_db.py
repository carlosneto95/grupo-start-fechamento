"""
Carrega um .xlsx já extraído (data/raw/contas_pagar_*.xlsx) para o banco,
sem precisar rodar a API de novo. Útil para validar o dashboard com os dados
que já temos.

Uso:
    python scripts/importar_xlsx_para_db.py data/raw/contas_pagar_EMPRESA1_2026-08.xlsx
"""
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from financeiro.db import init_db
from financeiro.escopo import SISTEMA
from financeiro.repositorio_contas_pagar import COLUNAS, upsert_contas


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_xlsx_para_db.py <caminho_do_xlsx>")
        return

    caminho = Path(sys.argv[1])
    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}")
        return

    init_db()

    df = pd.read_excel(caminho)
    df = df.where(pd.notna(df), None)

    faltando = set(COLUNAS) - set(df.columns)
    if faltando:
        print(f"Aviso: colunas ausentes no arquivo (vão ficar vazias): {faltando}")

    linhas = df.to_dict(orient="records")
    for linha in linhas:
        linha["id"] = str(linha.get("id"))

    upsert_contas(SISTEMA, linhas)
    print(f"{len(linhas)} linha(s) importada(s) de {caminho} para o banco.")


if __name__ == "__main__":
    main()
