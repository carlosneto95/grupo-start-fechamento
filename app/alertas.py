"""Alertas de anomalia (Fase 4.5).

Três regras sobre as contas a pagar CONSIDERADAS e dentro da visão (competência
>= ANO_MINIMO), todas dentro do escopo de quem olha:

  1. Possível pagamento duplicado — mesma empresa, fornecedor e valor, com
     vencimentos a até N dias um do outro e (por padrão) o MESMO histórico.
     Por que o histórico: no banco real, sem ele a regra dava mais de mil pares
     com vencimento idêntico, quase todos legítimos (placas de veículo e ordens
     de compra diferentes no histórico). Duplicidade de verdade é o lançamento
     digitado ou importado duas vezes, e esse repete o histórico. Comparar é
     com espaços colapsados e sem diferenciar maiúscula — só na comparação; o
     dado segue espelho do Tiny.
  2. Fornecedor novo acima de um valor — o primeiro lançamento dele (em todo o
     banco, inclusive antes de 2026: "novo" é novo para a empresa, não para a
     visão) aconteceu há até N dias, e o total considerado passa do mínimo.
  3. Categoria fora do padrão — despesa da categoria (por empresa) no mês,
     contra a média dos 3 meses anteriores: alerta se a variação passa de X% E
     de R$ Y. O piso em reais evita alerta de categoria pequena que dobrou de
     R$ 100 para R$ 200. Só meses COMPLETOS (anteriores ao mês corrente) e com
     3 meses de base dentro da visão: em 2026, a partir de 04/2026.

Os limites vêm da tabela `parametros_alerta` (migração 6), editada pelo Admin.
Alerta revisado pode ser DISPENSADO com motivo (tabela `alertas_dispensados`,
auditado): sai dos ativos, mas continua na lista marcado como dispensado.
Nada aqui altera conta: o alerta aponta, a correção (se houver) é no Tiny.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from app import auditoria
from app.db import FUSO_BRASILIA, agora_brasilia, get_conn
from app.dinheiro import ZERO, para_reais
from app.escopo import clausula, exigir_admin, exigir_escrita
from app.repositorio_contas_pagar import listar_contas
from app.visao import ANO_MINIMO, competencia_visivel, formatar_valor

TIPOS = {
    "duplicado": "Possível duplicidade",
    "fornecedor_novo": "Fornecedor novo",
    "categoria": "Categoria fora do padrão",
}


@dataclass(frozen=True)
class Parametro:
    """Descrição de um limite para a tela do Admin. O VALOR não está aqui:
    está na tabela. Aqui ficam só rótulo, unidade e a faixa aceita."""

    chave: str
    rotulo: str
    unidade: str  # "dias", "reais", "%", "sim/não"
    minimo: int
    maximo: int
    ajuda: str


PARAMETROS = [
    Parametro(
        "duplicado_janela_dias",
        "Duplicidade: vencimentos a até",
        "dias",
        0,
        20,
        # Teto medido: com 31 dias a regra pega a recorrência mensal (aluguel,
        # parcela) e passa de 2 mil pares.
        "Até 20: com um mês ou mais, a regra confunde duplicidade com conta mensal.",
    ),
    Parametro(
        "duplicado_exigir_historico_igual",
        "Duplicidade: exigir histórico igual",
        "sim/não",
        0,
        1,
        "Sem esta exigência, placas e ordens de compra diferentes viram alerta.",
    ),
    Parametro(
        "fornecedor_novo_dias",
        "Fornecedor novo: primeiro lançamento há até",
        "dias",
        1,
        365,
        "Conta desde o primeiro lançamento do fornecedor na empresa, em todo o histórico.",
    ),
    Parametro(
        "fornecedor_novo_valor_minimo_centavos",
        "Fornecedor novo: total a partir de",
        "reais",
        0,
        10**11,
        "Soma das contas consideradas do fornecedor novo.",
    ),
    Parametro(
        "categoria_variacao_pct",
        "Categoria: variação a partir de",
        "%",
        1,
        10_000,
        "Contra a média dos 3 meses anteriores (para mais ou para menos).",
    ),
    Parametro(
        "categoria_variacao_valor_minimo_centavos",
        "Categoria: e diferença a partir de",
        "reais",
        0,
        10**11,
        "Piso em reais, para categoria pequena não gerar alerta.",
    ),
]
POR_CHAVE = {p.chave: p for p in PARAMETROS}


# ---- parâmetros --------------------------------------------------------------------


def parametros() -> dict[str, int]:
    conn = get_conn()
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT chave, valor FROM parametros_alerta")}
    finally:
        conn.close()


def definir_parametros(escopo, novos: dict[str, int]) -> list[str]:
    """Grava os limites (só Admin). Devolve as chaves que mudaram; cada mudança
    vai para a auditoria com antes e depois. Valor fora da faixa -> ValueError,
    e nada é gravado (uma transação só)."""
    exigir_admin(escopo)
    for chave, valor in novos.items():
        p = POR_CHAVE.get(chave)
        if p is None:
            raise ValueError(f"parâmetro desconhecido: {chave}")
        if not isinstance(valor, int) or not p.minimo <= valor <= p.maximo:
            raise ValueError(f"{p.rotulo}: fora da faixa aceita")
    atuais = parametros()
    mudaram = [c for c, v in novos.items() if atuais.get(c) != v]
    if not mudaram:
        return []
    conn = get_conn()
    try:
        for chave in mudaram:
            conn.execute(
                "UPDATE parametros_alerta SET valor = ?, alterado_em = ?, alterado_por = ? "
                "WHERE chave = ?",
                (novos[chave], agora_brasilia(), escopo.login, chave),
            )
            auditoria.registrar(
                conn, "alterar_parametro_alerta", "parametros_alerta", chave, None,
                {"valor": atuais.get(chave)}, {"valor": novos[chave]},
            )  # fmt: skip
        conn.commit()
    finally:
        conn.close()
    return mudaram


# ---- cálculo -----------------------------------------------------------------------


def _data(texto: str | None) -> date | None:
    """Data do Tiny "DD/MM/AAAA"; torta ou vazia = None (é pendência, não alerta)."""
    try:
        return datetime.strptime((texto or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _normalizar(texto: str | None) -> str:
    """Só para COMPARAR históricos: espaços colapsados, sem caixa."""
    return " ".join((texto or "").split()).casefold()


def _historicos(escopo, chaves: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Histórico das contas candidatas a duplicidade. O listar_contas não traz
    o histórico (texto longo, não é coluna de tela); ler só das candidatas
    evita carregar o texto de 17 mil contas."""
    if not chaves:
        return {}
    filtro, params = clausula(escopo)
    conn = get_conn()
    try:
        saida = {}
        lista = sorted(chaves)
        # Lotes: o SQLite limita o número de parâmetros por consulta.
        for i in range(0, len(lista), 400):
            lote = lista[i : i + 400]
            marcas = ", ".join("(?, ?)" for _ in lote)
            planos = [v for par in lote for v in par]
            for empresa, id_, historico in conn.execute(
                f"SELECT empresa, id, historico FROM contas_pagar "
                f"WHERE (empresa, id) IN (VALUES {marcas}) AND {filtro}",
                [*planos, *params],
            ):
                saida[(empresa, str(id_))] = historico
        return saida
    finally:
        conn.close()


def _alerta(tipo, empresa, descricao, competencia, valor, detalhe, chave, filtros) -> dict:
    return {
        "chave": chave,
        "tipo": tipo,
        "tipo_rotulo": TIPOS[tipo],
        "empresa": empresa,
        "descricao": descricao,
        "competencia": competencia,
        "valor": valor,
        "detalhe": detalhe,
        "situacao": "ativo",
        "motivo": None,
        "dispensado_por": None,
        # Ver as linhas na tela de Despesas, pelos filtros de coluna dela.
        "rota": "despesas.listar",
        "filtros": filtros,
    }


def _duplicados(escopo, visiveis, p) -> list[dict]:
    janela = p["duplicado_janela_dias"]
    grupos = defaultdict(list)
    for c in visiveis:
        venc = _data(c["data_vencimento"])
        if venc and c["fornecedor"] and c["valor"]:
            grupos[(c["empresa"], c["fornecedor"], c["valor_centavos"])].append((venc, c))

    # 1ª passada: só grupos com dois ou mais lançamentos dentro da janela.
    candidatos = []
    for chave, itens in grupos.items():
        itens.sort(key=lambda x: (x[0], str(x[1]["id"])))
        if any((b[0] - a[0]).days <= janela for a, b in zip(itens, itens[1:])):
            candidatos.append((chave, itens))

    historicos = {}
    if p["duplicado_exigir_historico_igual"]:
        historicos = _historicos(
            escopo, {(c["empresa"], str(c["id"])) for _, itens in candidatos for _, c in itens}
        )

    saida = []
    for (empresa, fornecedor, _centavos), itens in candidatos:
        # Subgrupos por histórico (ou um só, se a exigência estiver desligada).
        por_historico = defaultdict(list)
        for venc, c in itens:
            h = _normalizar(historicos.get((empresa, str(c["id"])))) if historicos else ""
            por_historico[h].append((venc, c))
        for lista in por_historico.values():
            # Cadeias de vencimentos vizinhos (cada um a até `janela` do anterior):
            # três lançamentos iguais no mesmo dia são UM alerta, não três pares.
            cadeia = [lista[0]]
            for atual in lista[1:] + [None]:
                if atual is not None and (atual[0] - cadeia[-1][0]).days <= janela:
                    cadeia.append(atual)
                    continue
                if len(cadeia) > 1:
                    contas = [c for _, c in cadeia]
                    valor = contas[0]["valor"]
                    datas = sorted({c["data_vencimento"] for c in contas})
                    saida.append(
                        _alerta(
                            "duplicado",
                            empresa,
                            fornecedor,
                            contas[0]["competencia"],
                            # Em risco: o que se pagaria a mais se só um for devido.
                            valor * (len(contas) - 1),
                            f"{len(contas)} lançamentos de R$ {formatar_valor(valor)}, "
                            f"vencimento {', '.join(datas)}",
                            "duplicado:{}:{}".format(
                                empresa, "+".join(sorted(str(c["id"]) for c in contas))
                            ),
                            {
                                "empresa": empresa,
                                "fornecedor": fornecedor,
                                "data_vencimento": datas,
                            },
                        )
                    )
                if atual is not None:
                    cadeia = [atual]
    return saida


def _primeiras_aparicoes(escopo) -> dict[tuple[str, str], date]:
    """Primeiro lançamento de cada (empresa, fornecedor) em TODO o banco.

    Lido direto da tabela, não do listar_contas: aquele já corta competência
    anterior a ANO_MINIMO, e um fornecedor de 2025 passaria por "novo" em
    2026. Aqui o corte da visão não vale — "novo" é novo para a empresa."""
    filtro, params = clausula(escopo)
    conn = get_conn()
    try:
        linhas = conn.execute(
            f"SELECT empresa, fornecedor, data_emissao, data_vencimento FROM contas_pagar "
            f"WHERE fornecedor IS NOT NULL AND fornecedor <> '' AND {filtro}",
            params,
        ).fetchall()
    finally:
        conn.close()
    primeira: dict[tuple[str, str], date] = {}
    for empresa, fornecedor, emissao, vencimento in linhas:
        quando = _data(emissao) or _data(vencimento)
        chave = (empresa, fornecedor)
        if quando and (chave not in primeira or quando < primeira[chave]):
            primeira[chave] = quando
    return primeira


def _fornecedores_novos(escopo, visiveis, p, hoje: date) -> list[dict]:
    dias, minimo = p["fornecedor_novo_dias"], para_reais(p["fornecedor_novo_valor_minimo_centavos"])
    primeira = _primeiras_aparicoes(escopo)
    totais = defaultdict(lambda: [ZERO, 0, None])
    for c in visiveis:
        chave = (c["empresa"], c["fornecedor"])
        inicio = primeira.get(chave)
        if inicio and 0 <= (hoje - inicio).days <= dias:
            t = totais[chave]
            t[0] += c["valor"] or ZERO
            t[1] += 1
            t[2] = min(filter(None, [t[2], c["competencia"]]), key=lambda m: (m[3:], m[:2]))
    saida = []
    for (empresa, fornecedor), (total, quantidade, competencia) in totais.items():
        if total >= minimo:
            inicio = primeira[(empresa, fornecedor)]
            saida.append(
                _alerta(
                    "fornecedor_novo",
                    empresa,
                    fornecedor,
                    competencia,
                    total,
                    f"primeiro lançamento em {inicio:%d/%m/%Y}; {quantidade} lançamento(s)",
                    f"fornecedor_novo:{empresa}:{fornecedor}",
                    {"empresa": empresa, "fornecedor": fornecedor},
                )
            )
    return saida


def _meses_avaliados(hoje: date) -> list[str]:
    """De 01/ANO_MINIMO até o último mês completo (o anterior ao corrente)."""
    meses = []
    ano, mes = ANO_MINIMO, 1
    while (ano, mes) < (hoje.year, hoje.month):
        meses.append(f"{mes:02d}/{ano}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def _categorias(visiveis, p, hoje: date) -> list[dict]:
    pct, minimo = (
        p["categoria_variacao_pct"],
        para_reais(p["categoria_variacao_valor_minimo_centavos"]),
    )
    meses = _meses_avaliados(hoje)
    por = defaultdict(lambda: defaultdict(lambda: ZERO))
    for c in visiveis:
        if (c["categoria_primaria"] or "").strip():
            por[(c["empresa"], c["categoria_primaria"])][c["competencia"]] += c["valor"] or ZERO
    saida = []
    for (empresa, categoria), valores in por.items():
        for i in range(3, len(meses)):
            base = sum((valores[m] for m in meses[i - 3 : i]), ZERO) / 3
            atual = valores[meses[i]]
            diferenca = atual - base
            if abs(diferenca) < minimo or (base and abs(diferenca) / base * 100 < pct):
                continue
            variacao = f"{diferenca / base * 100:+.0f}%".replace(".", ",") if base else "sem base"
            saida.append(
                _alerta(
                    "categoria",
                    empresa,
                    categoria,
                    meses[i],
                    atual,
                    f"média dos 3 meses anteriores R$ {formatar_valor(base)}; variação {variacao}",
                    f"categoria:{empresa}:{categoria}:{meses[i]}",
                    {"empresa": empresa, "categoria_primaria": categoria, "competencia": meses[i]},
                )
            )
    return saida


def _dispensados(escopo) -> dict[str, dict]:
    filtro, params = clausula(escopo)
    conn = get_conn()
    try:
        return {
            r["chave"]: dict(r)
            for r in conn.execute(
                f"SELECT chave, motivo, dispensado_em, dispensado_por FROM alertas_dispensados "
                f"WHERE {filtro}",
                params,
            )
        }
    finally:
        conn.close()


def calcular(escopo, hoje: date | None = None) -> list[dict]:
    """Todos os alertas dentro do escopo: ativos primeiro, depois dispensados."""
    hoje = hoje or datetime.now(FUSO_BRASILIA).date()
    p = parametros()
    todas = listar_contas(escopo, {}, ordenado=False)
    visiveis = [
        c for c in todas if c["considerar_efetivo"] and competencia_visivel(c["competencia"])
    ]
    alertas = (
        _duplicados(escopo, visiveis, p)
        + _fornecedores_novos(escopo, visiveis, p, hoje)
        + _categorias(visiveis, p, hoje)
    )
    dispensados = _dispensados(escopo)
    for a in alertas:
        d = dispensados.get(a["chave"])
        if d:
            a.update(situacao="dispensado", motivo=d["motivo"], dispensado_por=d["dispensado_por"])
    # Ordem de TIPOS = ordem de urgência: duplicidade é dinheiro saindo em
    # dobro; fornecedor novo pede checagem de cadastro; categoria é tendência.
    ordem = list(TIPOS)
    alertas.sort(key=lambda a: (a["situacao"] != "ativo", ordem.index(a["tipo"]), -a["valor"]))
    return alertas


def resumo(alertas: list[dict]) -> dict[str, int]:
    """Ativos por tipo, para o cartão da tela de Pendências."""
    contagem = {t: 0 for t in TIPOS}
    for a in alertas:
        if a["situacao"] == "ativo":
            contagem[a["tipo"]] += 1
    return contagem


# ---- dispensar / reativar ----------------------------------------------------------


class AlertaNaoEncontrado(LookupError):
    """Chave que não existe no cálculo atual ou fora do escopo (a rota responde 404)."""


def dispensar(escopo, chave: str, motivo: str, hoje: date | None = None) -> None:
    """Marca o alerta como revisado. A chave precisa existir no cálculo feito
    com o escopo de quem pede — assim não se dispensa alerta inventado nem de
    empresa que não se enxerga."""
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ValueError("Escreva o motivo (mínimo 5 caracteres).")
    alerta = next((a for a in calcular(escopo, hoje) if a["chave"] == chave), None)
    if alerta is None or not exigir_escrita(escopo, alerta["empresa"]):
        raise AlertaNaoEncontrado(chave)
    if alerta["situacao"] == "dispensado":
        return
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO alertas_dispensados "
            "(chave, tipo, empresa, motivo, dispensado_em, dispensado_por) VALUES (?, ?, ?, ?, ?, ?)",
            (chave, alerta["tipo"], alerta["empresa"], motivo, agora_brasilia(), escopo.login),
        )
        auditoria.registrar(
            conn, "dispensar_alerta", "alerta", chave, alerta["empresa"], None, {"motivo": motivo}
        )
        conn.commit()
    finally:
        conn.close()


def reativar(escopo, chave: str) -> None:
    filtro, params = clausula(escopo)
    conn = get_conn()
    try:
        linha = conn.execute(
            f"SELECT empresa, motivo FROM alertas_dispensados WHERE chave = ? AND {filtro}",
            [chave, *params],
        ).fetchone()
        if linha is None or not exigir_escrita(escopo, linha["empresa"]):
            raise AlertaNaoEncontrado(chave)
        conn.execute("DELETE FROM alertas_dispensados WHERE chave = ?", (chave,))
        auditoria.registrar(
            conn,
            "reativar_alerta",
            "alerta",
            chave,
            linha["empresa"],
            {"motivo": linha["motivo"]},
            None,
        )
        conn.commit()
    finally:
        conn.close()
