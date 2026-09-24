"""Golden master: o código atual reproduz a fotografia congelada, ao centavo.

Roda só localmente — o CI não tem (e não pode ter) o banco real. Sem o
esperado, o teste é PULADO com aviso, não aprovado em silêncio: o resultado do
PR tem de dizer "golden: pulado" quando não rodou.

Se falhar, a mensagem lista cada número que mudou com o caminho até ele
(ex.: dashboard|MSV|03/2026.servicos.OBRA X.adm1: 1200.0 -> 1180.0). É a
explicação linha a linha exigida antes de seguir.
"""

import json
from pathlib import Path

import pytest

from tests.golden import fotografia
from tests.golden.gerar import ESPERADO, sha256

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def esperado():
    arquivo = ESPERADO / "fotografia.json"
    base = ESPERADO / "base.db"
    if not arquivo.exists() or not base.exists():
        pytest.skip("golden não gerado nesta máquina (tests/golden/esperado/ fica fora do git)")
    meta = json.loads((ESPERADO / "meta.json").read_text(encoding="utf-8"))
    # A base não pode ter mudado: se mudou, a comparação mediria dado, não código.
    assert sha256(base) == meta["sha256_base"], "base.db do golden foi alterada"
    return json.loads(arquivo.read_text(encoding="utf-8")), base


def test_fotografia_identica(esperado):
    foto_esperada, base = esperado
    obtida = json.loads(json.dumps(fotografia.tirar(Path(base), progresso=lambda *_: None)))
    diferencas = fotografia.comparar(foto_esperada, obtida)
    if diferencas:
        amostra = "\n".join(diferencas[:60])
        resto = f"\n... e mais {len(diferencas) - 60}" if len(diferencas) > 60 else ""
        pytest.fail(f"{len(diferencas)} diferença(s) no golden master:\n{amostra}{resto}")
