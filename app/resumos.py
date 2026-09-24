"""Agregações para o dashboard: quanto cada categoria custou.

Recebe as contas já filtradas e já restritas às consideradas — decidir o que
entra na conta é responsabilidade de quem chama, não daqui.
"""
from __future__ import annotations


SEM_CATEGORIA = "(sem categoria)"











# Tipos das colunas dos quadros de resultado (ver app/centros_de_custo.py),
# para a ordenação por cabeçalho.
# "movimento" é a coluna oculta usada como ordem padrão: receita + despesa,
# ou seja, quem mexe mais dinheiro aparece primeiro.
TIPOS_ORDENACAO_RESULTADO = {
    "nome": "texto",
    "receita": "numero",
    "despesa": "numero",
    "imposto": "numero",
    "adm1": "numero",
    "adm2": "numero",
    "custo_total": "numero",
    "resultado": "numero",
    "margem": "numero",
    "movimento": "numero",
}


def arvore_de_gastos(contas: list[dict], niveis=("categoria_primaria", "subcategoria", "fornecedor")) -> dict:
    """Hierarquia de despesa para a visão expansível: cada nível soma os filhos.

    Devolve {"itens": [...], "total": float}. Cada item tem nome, valor,
    percentual (sobre o total geral, para as barras/percentuais serem
    comparáveis entre níveis) e a lista de filhos."""
    total = sum(c.get("valor") or 0 for c in contas)

    def agrupar(linhas: list[dict], profundidade: int) -> list[dict]:
        if profundidade >= len(niveis):
            return []
        campo = niveis[profundidade]

        grupos: dict[str, list[dict]] = {}
        for linha in linhas:
            grupos.setdefault(linha.get(campo) or SEM_CATEGORIA, []).append(linha)

        itens = []
        for nome, filhas in grupos.items():
            valor = sum(f.get("valor") or 0 for f in filhas)
            itens.append({
                "nome": nome,
                "valor": valor,
                "quantidade": len(filhas),
                "percentual": (valor / total * 100) if total else 0.0,
                "filhos": agrupar(filhas, profundidade + 1),
            })
        itens.sort(key=lambda i: i["valor"], reverse=True)
        return itens

    return {"itens": agrupar(contas, 0), "total": total}
