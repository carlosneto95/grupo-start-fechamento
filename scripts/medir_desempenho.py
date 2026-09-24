"""Mede o tempo das rotas mais pesadas sobre o banco congelado do golden.

    .venv\\Scripts\\python scripts\\medir_desempenho.py [--vezes 7]

Usa a mesma cópia congelada do golden master (tests/golden/esperado/base.db)
para que "antes" e "depois" meçam o CÓDIGO sobre os MESMOS dados. Mostra a
mediana de N execuções depois de 1 aquecimento: a primeira chamada paga import
e cache de template, que não é o tempo que o usuário sente no dia a dia.

Não grava nada no git: só imprime. Os tempos entram no HISTORICO.md.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import tests.conftest as base_testes  # noqa: E402  (desvia o banco antes de tudo)
from tests.golden import fotografia  # noqa: E402

# Rotas medidas: a tela inteira de Despesas (a de mais linhas), o Dashboard e
# os funis mais caros — o de fornecedor (1.400+ valores) e o de competência.
ROTAS = [
    "/despesas",
    "/dashboard",
    "/receitas/servicos",
    "/api/valores-filtro?tabela=despesas&coluna=fornecedor",
    "/api/valores-filtro?tabela=despesas&coluna=competencia",
    "/api/valores-filtro?tabela=despesas&coluna=fornecedor&empresa=MSV",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vezes", type=int, default=7)
    args = ap.parse_args()

    base = RAIZ / "tests" / "golden" / "esperado" / "base.db"
    if not base.exists():
        print("Sem tests/golden/esperado/base.db: gere o golden antes.")
        return 1

    with fotografia._banco_temporario(base) as copia:
        cliente = base_testes.cliente_para(copia)
        print(f"{'rota':62} {'mediana':>9} {'mín':>8} {'máx':>8}")
        for rota in ROTAS:
            cliente.get(rota)  # aquecimento
            tempos = []
            for _ in range(args.vezes):
                t0 = time.perf_counter()
                r = cliente.get(rota)
                tempos.append((time.perf_counter() - t0) * 1000)
                assert r.status_code == 200, (rota, r.status_code)
            print(
                f"{rota:62} {statistics.median(tempos):7.0f}ms "
                f"{min(tempos):6.0f}ms {max(tempos):6.0f}ms"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
