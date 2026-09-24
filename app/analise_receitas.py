"""Agregação da tela de Análise de Receitas.

A tela é uma grade **categoria × mês**: cada linha é uma categoria primária
efetiva, cada coluna é uma competência, e a célula é o faturamento daquela
categoria naquele mês. As categorias descem na vertical, uma embaixo da outra,
e os meses correm na horizontal — a leitura é por linha, acompanhando um
contrato mês a mês.

A grade é partida em dois blocos, Vendas e Serviços, porque as duas populações
não se cruzam: nenhuma categoria aparece nos dois tipos de nota (a única exceção
é a grafia divergente SERVIÇO EXTERNOS × SERVIÇOS EXTERNOS, que é sujeira do
ERP e se reporta, não se conserta aqui). Juntas num bloco só, cada linha teria 25
colunas das quais 22 estariam vazias.

Recebe as notas já filtradas e já restritas às consideradas — decidir o que entra
na conta é de quem chama, como em `app/resumos.py`.
"""
from __future__ import annotations

from app.resumos import SEM_CATEGORIA

# Blocos da tela, na ordem em que aparecem. A chave é o `tipo_nota` do banco.
BLOCOS = (("venda", "Vendas"), ("servico", "Serviços"))

MESES_PT = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")


def _ordem_competencia(competencia: str) -> tuple[int, int]:
    """"MM/AAAA" ordenado como data. Texto puro colocaria 01/2027 antes de 12/2026."""
    mes, _, ano = (competencia or "").partition("/")
    if mes.isdigit() and ano.isdigit():
        return (int(ano), int(mes))
    return (9999, 99)  # competência fora do formato vai para o fim, visível


def nome_do_mes(competencia: str) -> str:
    """"08/2026" -> "Agosto". Aceita mês fora de 01-12 sem quebrar: o ERP às
    vezes traz sujeira (existe uma competência 07/2800 no banco) e a regra do
    projeto é mostrar o que está lá, não corrigir."""
    mes, _, _ano = (competencia or "").partition("/")
    if mes.isdigit() and 1 <= int(mes) <= 12:
        return MESES_PT[int(mes) - 1]
    return ""


def _bloco(notas: list[dict], competencias: list[str], titulo: str) -> dict:
    """Uma grade categoria × mês.

    As competências vêm de FORA (a lista completa do recorte, não só as deste
    bloco) para que as duas grades tenham exatamente as mesmas colunas. Sem
    isso, um mês em que só houve serviço faria os dois blocos desalinharem e a
    comparação de um sobre o outro deixaria de funcionar.
    """
    indice = {c: i for i, c in enumerate(competencias)}

    # {categoria: [valor por mês]} e {categoria: [quantidade por mês]}
    valores: dict[str, list[float]] = {}
    quantidades: dict[str, list[int]] = {}

    for nota in notas:
        categoria = (nota.get("categoria_primaria_efetiva") or "").strip() or SEM_CATEGORIA
        competencia = (nota.get("competencia_efetiva") or "").strip() or "—"
        if competencia not in indice:
            continue
        serie = valores.setdefault(categoria, [0.0] * len(competencias))
        conta = quantidades.setdefault(categoria, [0] * len(competencias))
        i = indice[competencia]
        serie[i] += nota.get("valor") or 0
        conta[i] += 1

    total_bloco = sum(sum(v) for v in valores.values())

    # Linhas ordenadas da maior para a menor receita: a categoria que mais pesa
    # fica no topo, onde o olho cai primeiro.
    linhas = []
    for nome, serie in valores.items():
        conta = quantidades[nome]
        total = sum(serie)
        ativos = sum(1 for v in serie if v)
        linhas.append({
            "nome": nome,
            "celulas": [{"valor": v, "quantidade": q} for v, q in zip(serie, conta)],
            "total": total,
            "quantidade": sum(conta),
            "percentual": (total / total_bloco * 100) if total_bloco else 0.0,
            "meses_ativos": ativos,
            # Média por mês ATIVO, não pelo número de colunas: uma categoria que
            # começou a faturar em maio teria a média diluída pelos meses em que
            # o contrato nem existia.
            "media": (total / ativos) if ativos else 0.0,
        })
    linhas.sort(key=lambda l: l["total"], reverse=True)

    colunas = []
    for i, competencia in enumerate(competencias):
        total_mes = sum(l["celulas"][i]["valor"] for l in linhas)
        colunas.append({
            "competencia": competencia,
            "mes": nome_do_mes(competencia),
            "total": total_mes,
            "quantidade": sum(l["celulas"][i]["quantidade"] for l in linhas),
            "percentual": (total_mes / total_bloco * 100) if total_bloco else 0.0,
        })

    meses_com_receita = sum(1 for c in colunas if c["total"])

    return {
        "titulo": titulo,
        "colunas": colunas,
        "linhas": linhas,
        "total": total_bloco,
        "quantidade": sum(l["quantidade"] for l in linhas),
        "meses_com_receita": meses_com_receita,
        "media_mensal": (total_bloco / meses_com_receita) if meses_com_receita else 0.0,
    }


def grades(notas: list[dict]) -> dict:
    """Monta os dois blocos e o consolidado.

    {"blocos": [Vendas, Serviços], "competencias": [...], "total": float, ...}
    """
    competencias = sorted(
        {(n.get("competencia_efetiva") or "").strip() or "—" for n in notas},
        key=_ordem_competencia,
    )

    blocos = []
    for tipo, titulo in BLOCOS:
        do_tipo = [n for n in notas if (n.get("tipo_nota") or "") == tipo]
        # Bloco sem nenhuma nota no recorte não vira tabela vazia na tela.
        if do_tipo:
            blocos.append(_bloco(do_tipo, competencias, titulo))

    # Notas de um tipo que não está em BLOCOS. Não deveria existir, mas se o ERP
    # passar a emitir outro tipo, ele aparece de propósito em vez de sumir da
    # soma e fazer o total da tela não bater com o das telas de listagem.
    conhecidos = {tipo for tipo, _ in BLOCOS}
    outras = [n for n in notas if (n.get("tipo_nota") or "") not in conhecidos]
    if outras:
        blocos.append(_bloco(outras, competencias, "Outros"))

    total = sum(b["total"] for b in blocos)
    # Mês conta uma vez só, mesmo faturando nos dois blocos.
    meses_com_receita = len({
        c["competencia"] for b in blocos for c in b["colunas"] if c["total"]
    })

    return {
        "blocos": blocos,
        "competencias": competencias,
        "total": total,
        "quantidade": len(notas),
        "meses": len(competencias),
        "meses_com_receita": meses_com_receita,
        "media_mensal": (total / meses_com_receita) if meses_com_receita else 0.0,
        "categorias": sum(len(b["linhas"]) for b in blocos),
    }
