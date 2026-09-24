"""
Atalho mantido por compatibilidade: sincroniza SÓ as notas (receitas).

Desde a Fase 1 existe um job único (app/sincronizar_tudo.py) para despesas
e notas; este script só chama `scripts/sincronizar.py ... --so notas`, com
histórico gravado em `sincronizacoes` como qualquer outra execução.

Uso:
    python scripts/sincronizar_receitas.py MSV                 # ano atual
    python scripts/sincronizar_receitas.py TODAS --desde 2025-01-01 --ate 2026-12-31
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sincronizar  # noqa: E402

if __name__ == "__main__":
    if "--so" not in sys.argv:
        sys.argv += ["--so", "notas"]
    raise SystemExit(sincronizar.main())
