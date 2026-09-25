"""Confere o banco carregado no servidor contra o manifesto gerado no computador.

    python deploy/conferir_carga.py data/app.db manifesto.json [--hash]

Com --hash, confere também o SHA-256 do arquivo (logo depois de descompactar,
antes de qualquer migração). Sem --hash, confere os NÚMEROS — contagens, somas
em centavos e ajustes manuais por empresa —, que continuam valendo depois das
migrações (migração nova cria tabela, não mexe nessas).

Sai com código 1 e a lista de divergências se algo não bater.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from empacotar_carga import manifesto, sha256  # noqa: E402  (mesma função dos dois lados)


def divergencias(esperado: dict, obtido: dict) -> list[str]:
    difs = []
    # Tabelas do manifesto têm de existir com a mesma contagem; tabela NOVA
    # (criada por migração no servidor) não é divergência.
    for tabela, n in esperado["tabelas"].items():
        if obtido["tabelas"].get(tabela) != n:
            difs.append(f"tabela {tabela}: esperado {n}, obtido {obtido['tabelas'].get(tabela)}")
    for chave in ("contas_pagar", "notas", "notas_ajustadas"):
        if esperado[chave] != obtido[chave]:
            difs.append(f"{chave}: esperado {esperado[chave]}, obtido {obtido[chave]}")
    if obtido["integridade"] != "ok":
        difs.append(f"integridade: {obtido['integridade']}")
    return difs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("banco")
    ap.add_argument("manifesto")
    ap.add_argument("--hash", action="store_true")
    args = ap.parse_args()
    esperado = json.loads(Path(args.manifesto).read_text(encoding="utf-8"))
    if args.hash and sha256(Path(args.banco)) != esperado["sha256"]:
        print("ERRO: o arquivo do banco não é o que saiu do computador (SHA-256 diferente).")
        return 1
    difs = divergencias(esperado, manifesto(Path(args.banco)))
    for d in difs:
        print("DIVERGÊNCIA:", d)
    if difs:
        return 1
    t = esperado["tabelas"]
    print(
        f"    conferido: {t.get('contas_pagar')} contas, {t.get('notas')} notas, "
        f"{esperado['notas_ajustadas']} notas ajustadas à mão, somas por empresa iguais."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
