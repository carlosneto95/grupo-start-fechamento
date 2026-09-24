"""Resultado por centro de custo, com imposto e administrativo rateados.

O grupo opera dois centros de custo sobre o mesmo plano de categorias. A
separação é por categoria primária: uma lista fechada é Vendas, o resto é
Serviços.

Cada categoria primária **com receita** é um contrato ou atividade com cliente.
Para medir a eficiência real de cada uma, a despesa direta não basta — é preciso
carregar nela a parte que lhe cabe do que não é direto:

  Imposto — 14% da receita em Vendas, 10% em Serviços.
  Adm I   — o ADM GERAL, despesa administrativa que atende os dois centros.
            Divide-se 10% Vendas / 90% Serviços e, dentro de cada bloco,
            rateia-se entre as categorias na proporção da receita de cada uma.
  Adm II  — o administrativo específico do centro: ADM MSV em Vendas,
            ADM START GTF em Serviços. Mesmo rateio proporcional à receita.

  Custo total = despesa + imposto + Adm I + Adm II
  Resultado   = receita − custo total

As categorias que ORIGINAM Adm I e Adm II (ADM GERAL, ADM MSV, ADM START GTF)
deixam de existir como linha: viram coluna. Mantê-las como linha contaria o
mesmo dinheiro duas vezes.

Categoria sem receita fica na tabela com rateio zero — proporcional a zero é
zero. Ela aparece como custo puro, que é exatamente o que é.

Categoria sem classificação no Tiny não é chutada para nenhum centro: vira bloco
próprio, sem imposto e sem rateio, visível de propósito para pressionar a
correção na origem.
"""
from __future__ import annotations

from app.resumos import SEM_CATEGORIA

# Categorias do centro de custo de Vendas. O resto é Serviços.
# IMPOSTO está aqui por decisão de negócio (é o imposto da MSV), mas hoje é
# letra morta: a regra de exclusão zera a categoria antes de ela chegar ao
# dashboard — e o imposto que conta agora é o calculado, não o do Tiny.
CATEGORIAS_VENDAS = {
    "COMERCIO",
    "INDUSTRIA",
    "DCA",
    "PROJETOS",
    "ADM MSV",
    "IMPOSTO",
}

# Origem do Adm I. "ADM GERAL INATIVO" é grafia divergente do mesmo centro de
# custo — o sistema é espelho do Tiny e não corrige o nome, mas para o rateio
# conta como ADM GERAL.
CATEGORIAS_ADM_GERAL = {"ADM GERAL", "ADM GERAL INATIVO"}

VENDAS = "Vendas"
SERVICOS = "Serviços"
SEM_CLASSIFICACAO = "Sem classificação"

# Origem do Adm II, por bloco.
CATEGORIA_ADM_PROPRIA = {VENDAS: "ADM MSV", SERVICOS: "ADM START GTF"}

# Divisão do ADM GERAL entre os centros, antes do rateio por categoria.
FRACAO_ADM_GERAL = {VENDAS: 0.10, SERVICOS: 0.90}

# Alíquota sobre a receita de cada categoria.
ALIQUOTA = {VENDAS: 0.14, SERVICOS: 0.10}

# Colunas rateadas: ficam None (e não 0,00) onde o rateio não se aplica, para a
# tela mostrar "—" em vez de um zero que pareceria cálculo feito.
CAMPOS_RATEADOS = ("imposto", "adm1", "adm2")


def _classificar(categoria: str | None) -> str:
    """Em que bloco a categoria cai. As de origem do Adm não caem em nenhum."""
    nome = (categoria or "").strip().upper()
    if not nome:
        return SEM_CLASSIFICACAO
    if nome in CATEGORIAS_ADM_GERAL:
        return ""  # vira Adm I
    if nome in CATEGORIA_ADM_PROPRIA.values():
        return ""  # vira Adm II
    return VENDAS if nome in CATEGORIAS_VENDAS else SERVICOS


def _linha(nome: str, rateia: bool = True) -> dict:
    base = {"nome": nome, "receita": 0.0, "despesa": 0.0,
            "qtd_receita": 0, "qtd_despesa": 0}
    base.update({campo: (0.0 if rateia else None) for campo in CAMPOS_RATEADOS})
    base["rateia"] = rateia
    return base


def _fechar(linha: dict) -> dict:
    """Soma o custo total e deriva resultado e margem."""
    linha["custo_total"] = linha["despesa"] + sum(
        linha[campo] or 0 for campo in CAMPOS_RATEADOS
    )
    linha["resultado"] = linha["receita"] - linha["custo_total"]
    # Sem receita não existe margem: None vira "—" na tela, e não um zero que
    # pareceria margem nula de verdade.
    linha["margem"] = (
        linha["resultado"] / linha["receita"] * 100 if linha["receita"] else None
    )
    # Coluna oculta usada como ordem padrão: quem mexe mais dinheiro vem antes.
    linha["movimento"] = linha["receita"] + linha["custo_total"]
    return linha


def separar(notas: list[dict], contas: list[dict]) -> dict:
    """Monta os quadros do dashboard já com imposto e administrativo rateados.

    {"resumo": [Vendas, Serviços, Sem classificação], "total": linha,
     "vendas": {"linhas": [...], "totais": linha}, "servicos": {...},
     "sem_classificacao": {...}, "rateio": {...}}
    """
    blocos: dict[str, dict[str, dict]] = {VENDAS: {}, SERVICOS: {}, SEM_CLASSIFICACAO: {}}

    # Fontes do rateio, acumuladas em vez de virar linha.
    adm_geral = 0.0
    adm_propria = {VENDAS: 0.0, SERVICOS: 0.0}

    def caixa(bloco: str, categoria: str | None) -> dict:
        nome = (categoria or "").strip() or SEM_CATEGORIA
        return blocos[bloco].setdefault(
            nome, _linha(nome, rateia=bloco != SEM_CLASSIFICACAO))

    for nota in notas:
        categoria = nota.get("categoria_primaria_efetiva")
        bloco = _classificar(categoria)
        # As categorias de Adm não têm receita hoje. Se passarem a ter, ela cai
        # em Serviços em vez de sumir — rateio de receita não foi combinado.
        linha = caixa(bloco or SERVICOS, categoria)
        linha["receita"] += nota.get("valor") or 0
        linha["qtd_receita"] += 1

    # De qual bloco cada categoria de Adm II é a fonte ("ADM MSV" -> Vendas).
    bloco_da_adm_propria = {v: k for k, v in CATEGORIA_ADM_PROPRIA.items()}

    for conta in contas:
        categoria = conta.get("categoria_primaria")
        nome = (categoria or "").strip().upper()
        valor = conta.get("valor") or 0

        # As categorias de Adm alimentam as colunas rateadas em vez de virar
        # linha — como linha, o mesmo dinheiro apareceria duas vezes.
        if nome in CATEGORIAS_ADM_GERAL:
            adm_geral += valor
        elif nome in bloco_da_adm_propria:
            adm_propria[bloco_da_adm_propria[nome]] += valor
        else:
            linha = caixa(_classificar(categoria), categoria)
            linha["despesa"] += valor
            linha["qtd_despesa"] += 1

    # ---- rateios -------------------------------------------------------
    rateio = {"adm_geral": adm_geral, "por_bloco": {}}

    for bloco in (VENDAS, SERVICOS):
        linhas = blocos[bloco].values()
        base_receita = sum(l["receita"] for l in linhas)
        cota_adm1 = adm_geral * FRACAO_ADM_GERAL[bloco]
        cota_adm2 = adm_propria[bloco]
        aliquota = ALIQUOTA[bloco]

        for linha in linhas:
            # Proporcional à receita: categoria sem receita recebe zero, e é
            # assim que ela deve aparecer — custo puro, sem contrato por trás.
            peso = (linha["receita"] / base_receita) if base_receita else 0.0
            linha["imposto"] = linha["receita"] * aliquota
            linha["adm1"] = cota_adm1 * peso
            linha["adm2"] = cota_adm2 * peso

        rateio["por_bloco"][bloco] = {
            "aliquota": aliquota,
            "adm1": cota_adm1,
            "adm2": cota_adm2,
            "categoria_adm2": CATEGORIA_ADM_PROPRIA[bloco],
            "base_receita": base_receita,
            "sem_receita": sum(1 for l in linhas if not l["receita"]),
        }

    # ---- fechamento ----------------------------------------------------
    def montar(nome_bloco: str) -> dict:
        linhas = [_fechar(l) for l in blocos[nome_bloco].values()]
        linhas.sort(key=lambda l: l["movimento"], reverse=True)
        totais = _linha(nome_bloco, rateia=nome_bloco != SEM_CLASSIFICACAO)
        for l in linhas:
            for campo in ("receita", "despesa", "qtd_receita", "qtd_despesa"):
                totais[campo] += l[campo]
            for campo in CAMPOS_RATEADOS:
                if totais[campo] is not None:
                    totais[campo] += l[campo] or 0
        return {"linhas": linhas, "totais": _fechar(totais)}

    vendas = montar(VENDAS)
    servicos = montar(SERVICOS)
    sem_classificacao = montar(SEM_CLASSIFICACAO)

    total = _linha("Total")
    for parte in (vendas, servicos, sem_classificacao):
        for campo in ("receita", "despesa", "qtd_receita", "qtd_despesa"):
            total[campo] += parte["totais"][campo]
        for campo in CAMPOS_RATEADOS:
            total[campo] += parte["totais"][campo] or 0

    resumo = [vendas["totais"], servicos["totais"]]
    # Só entra na tela se existir de verdade — linha zerada é ruído.
    if sem_classificacao["linhas"]:
        resumo.append(sem_classificacao["totais"])

    return {
        "resumo": resumo,
        "total": _fechar(total),
        "vendas": vendas,
        "servicos": servicos,
        "sem_classificacao": sem_classificacao,
        "rateio": rateio,
    }
