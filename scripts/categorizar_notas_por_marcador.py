"""
Preenche a categoria das notas de venda a partir dos MARCADORES do Tiny.

A NF-e não tem campo de categoria financeira no ERP, mas a equipe registra a
natureza da operação no marcador ("COMERCIO / REVENDA", "INDUSTRIALIZAÇÃO").
Este script lê esse marcador e grava a categoria correspondente.

Importante: grava em `categoria_manual`, a coluna de ajuste — o que veio do ERP
não é tocado, e a próxima sincronização não apaga o preenchimento.

Uso:
    python scripts/categorizar_notas_por_marcador.py MSV --simular
    python scripts/categorizar_notas_por_marcador.py MSV
    python scripts/categorizar_notas_por_marcador.py MSV --refazer   # inclui as já ajustadas
"""
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.receitas import definir_ajuste, listar_notas

# Marcador (sem acento, maiúsculo) -> categoria primária.
# Usamos os mesmos nomes das categorias de despesa para que o comparativo do
# dashboard confronte receita e despesa na mesma linha.
REGRAS = [
    ("INDUSTRIALIZA", "INDUSTRIA"),
    ("COMERCIO", "COMERCIO"),
]


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).upper()


def categoria_do_marcador(marcadores: str | None) -> str | None:
    """Devolve a categoria, ou None se o marcador não permitir decidir.

    Se a nota tiver marcadores de mais de uma natureza, devolve None em vez de
    escolher: chutar aqui produziria número errado no fechamento."""
    texto = _sem_acento(marcadores)
    achadas = {categoria for chave, categoria in REGRAS if chave in texto}
    return achadas.pop() if len(achadas) == 1 else None


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    simular = "--simular" in sys.argv
    refazer = "--refazer" in sys.argv

    if not argumentos:
        print(__doc__)
        return

    empresa = argumentos[0]
    notas = [n for n in listar_notas({"empresa": empresa}) if n["tipo_nota"] == "venda"]
    if not notas:
        print(f"Nenhuma nota de venda encontrada para {empresa}.")
        return

    decididas, indecisas, ja_ajustadas = [], [], []
    for nota in notas:
        if nota["categoria_manual"] and not refazer:
            ja_ajustadas.append(nota)
            continue
        categoria = categoria_do_marcador(nota["marcadores"])
        (decididas if categoria else indecisas).append((nota, categoria))

    print(f"{empresa}: {len(notas)} nota(s) de venda")
    print(f"  com categoria definida pelo marcador : {len(decididas)}")
    print(f"  sem marcador que permita decidir     : {len(indecisas)}")
    if ja_ajustadas:
        print(f"  já ajustadas antes (mantidas)        : {len(ja_ajustadas)}")

    contagem: dict[str, int] = {}
    for _, categoria in decididas:
        contagem[categoria] = contagem.get(categoria, 0) + 1
    print()
    for categoria, quantidade in sorted(contagem.items()):
        print(f"  {categoria}: {quantidade}")

    if indecisas:
        print("\n  ficam sem categoria:")
        for nota, _ in indecisas[:10]:
            print(f"    NF {nota['numero']} {nota['data_emissao']} R$ {nota['valor']:>10,.2f}"
                  f" — {(nota['marcadores'] or '')[:55]}")

    if simular:
        print(f"\nSIMULAÇÃO — nada gravado. Seriam preenchidas {len(decididas)} nota(s).")
        return

    for nota, categoria in decididas:
        definir_ajuste(nota["empresa"], nota["tipo_nota"], nota["id"], categoria=categoria)
    print(f"\nPreenchidas {len(decididas)} nota(s).")


if __name__ == "__main__":
    main()
