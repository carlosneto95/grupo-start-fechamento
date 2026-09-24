"""Agregações para o dashboard: quanto cada categoria custou.

Recebe as contas já filtradas e já restritas às consideradas — decidir o que
entra na conta é responsabilidade de quem chama, não daqui.
"""
from __future__ import annotations

from app.dinheiro import ZERO

SEM_CATEGORIA = "(sem categoria)"


def _acumular(destino: dict, chave: str, conta: dict) -> None:
    # Decimal: o valor chega do banco em reais exatos (app/dinheiro.py).
    linha = destino.setdefault(chave, {"valor": ZERO, "pago": ZERO, "quantidade": 0})
    linha["valor"] += conta.get("valor") or 0
    linha["pago"] += conta.get("pago") or 0
    linha["quantidade"] += 1


def _em_lista(agrupado: dict, total: float) -> list[dict]:
    """Vira lista ordenada do maior custo para o menor, já com o percentual."""
    itens = [
        {
            "nome": nome,
            "valor": dados["valor"],
            "pago": dados["pago"],
            "quantidade": dados["quantidade"],
            "percentual": (dados["valor"] / total * 100) if total else 0.0,
        }
        for nome, dados in agrupado.items()
    ]
    itens.sort(key=lambda i: i["valor"], reverse=True)
    return itens


def resumir_por_categoria(contas: list[dict]) -> dict:
    """Totais por categoria primária e por subcategoria.

    A subcategoria vem rotulada com a primária ("INDUSTRIA › FRETE") porque o mesmo
    nome de subcategoria aparece em primárias diferentes — FRETE existe tanto em
    INDUSTRIA quanto em COMERCIO, e somá-los juntos esconderia a diferença."""
    total = sum(c.get("valor") or 0 for c in contas)
    total_pago = sum(c.get("pago") or 0 for c in contas)

    primarias: dict[str, dict] = {}
    subcategorias: dict[str, dict] = {}

    for conta in contas:
        primaria = conta.get("categoria_primaria") or SEM_CATEGORIA
        sub = conta.get("subcategoria") or SEM_CATEGORIA
        _acumular(primarias, primaria, conta)
        _acumular(subcategorias, f"{primaria} › {sub}", conta)

    return {
        "total": total,
        "total_pago": total_pago,
        "primarias": _em_lista(primarias, total),
        "subcategorias": _em_lista(subcategorias, total),
    }


def resumir_receitas(notas: list[dict]) -> dict:
    """Totais de receita por categoria primária.

    Só a primária: a subcategoria das notas ("-RECEITA") não acrescenta nada
    para análise. Notas fora do faturamento já devem ter sido filtradas antes."""
    total = sum(n.get("valor") or 0 for n in notas)

    por_categoria: dict[str, dict] = {}
    por_empresa: dict[str, dict] = {}
    for nota in notas:
        _acumular(por_categoria, nota.get("categoria_primaria_efetiva") or SEM_CATEGORIA, nota)
        _acumular(por_empresa, nota.get("empresa") or "(sem empresa)", nota)

    return {
        "total": total,
        "categorias": _em_lista(por_categoria, total),
        "empresas": _em_lista(por_empresa, total),
    }



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
