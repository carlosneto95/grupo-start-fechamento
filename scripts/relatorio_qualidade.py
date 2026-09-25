"""Relatório de qualidade de dados — SÓ LEITURA.

Aponta a sujeira que chega do Tiny e o efeito dela na tela. Não corrige nada:
o sistema é espelho do ERP e a correção se faz lá (regra do CLAUDE.md).

    .venv\\Scripts\\python scripts\\relatorio_qualidade.py            # data/app.db
    .venv\\Scripts\\python scripts\\relatorio_qualidade.py --db x.db --saida relatorios\\q.md

O banco é aberto com `mode=ro`: nem o PRAGMA de WAL que o app roda ao conectar
acontece aqui. O resultado tem números reais, então vai para `relatorios/`,
que está fora do git.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Só funções PURAS do app: nenhuma delas abre conexão. Assim o relatório usa
# exatamente a mesma regra da tela sem passar pelo get_conn (que grava PRAGMA).
from financeiro.centros_de_custo import separar  # noqa: E402
from financeiro.db import abrir_somente_leitura  # noqa: E402
from financeiro.receitas import _enriquecer  # noqa: E402
from financeiro.repositorio_contas_pagar import _considerar_efetivo, _em_reais  # noqa: E402
from financeiro.visao import ANO_MINIMO, formatar_valor  # noqa: E402

BRT_OFFSET_H = -3  # horário de Brasília fixo (sem horário de verão desde 2019)


def rs(valor) -> str:
    return "R$ " + formatar_valor(valor)


def _ano_mes(comp: str | None):
    """ "07/2026" -> (2026, 7). Fora do formato -> None (é sujeira a reportar)."""
    mes, _, ano = str(comp or "").strip().partition("/")
    if mes.isdigit() and ano.isdigit() and len(ano) == 4:
        return int(ano), int(mes)
    return None


def carregar(caminho: Path):
    conn = abrir_somente_leitura(caminho)
    conn.row_factory = sqlite3.Row
    # O relatório abre SÓ LEITURA e não migra. Num banco anterior à migração 3
    # (dinheiro em centavos) ele mostraria R$ 0,00 em tudo sem avisar — o que
    # é pior que não rodar. Recusa e diz o que fazer.
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(contas_pagar)")}
    if "valor_centavos" not in colunas:
        conn.close()
        raise SystemExit(
            f"{caminho}: banco sem as migrações da Fase 1 (valor em centavos). "
            "Suba o sistema uma vez (python app.py) ou rode scripts/tarefa_diaria.py, "
            "que migram com backup, e gere o relatório de novo."
        )
    # _em_reais: desde a Fase 1 o banco guarda centavos; a regra usa reais.
    contas = [_em_reais(dict(r)) for r in conn.execute("SELECT * FROM contas_pagar")]
    notas = [_enriquecer(dict(r)) for r in conn.execute("SELECT * FROM notas")]
    regras: dict[str, list[str]] = {"categoria_primaria": [], "subcategoria": []}
    for r in conn.execute("SELECT tipo, valor FROM regras_exclusao"):
        regras.setdefault(r["tipo"], []).append(r["valor"])
    conn.close()
    for c in contas:
        c["considerar_efetivo"] = _considerar_efetivo(c, regras)
    return contas, notas, regras


def relatorio(caminho: Path, hoje: datetime) -> str:
    contas, notas, regras = carregar(caminho)
    out: list[str] = []
    p = out.append

    # Visão = o que a tela mostra hoje (FILTRO_SQL_CONTAS / FILTRO_SQL_NOTAS).
    def conta_visivel(c):
        # Réplica de FILTRO_SQL_CONTAS (financeiro/visao.py): competência vazia passa
        # (desde a Fase 1) e o resto é comparação de TEXTO do ano.
        comp = (c["competencia"] or "").strip()
        return not comp or comp[3:7] >= str(ANO_MINIMO)

    def nota_visivel(n):
        comp = (n["competencia_efetiva"] or "").strip()
        return not comp or comp[3:7] >= str(ANO_MINIMO)

    contas_vis = [c for c in contas if conta_visivel(c)]
    notas_vis = [n for n in notas if nota_visivel(n)]

    brt = timezone(timedelta(hours=BRT_OFFSET_H))
    p(f"# Relatório de qualidade de dados — {hoje.astimezone(brt):%d/%m/%Y %H:%M} (Brasília)\n")
    p(
        f"Banco: `{caminho}` · {len(contas)} contas ({len(contas_vis)} na visão) · "
        f"{len(notas)} notas ({len(notas_vis)} na visão)\n"
    )

    # ---- 1. Sincronização --------------------------------------------------
    p("## 1. Última sincronização por empresa e tipo\n")
    p("| Empresa | Tipo | Última gravação (Brasília) | Dias parada |")
    p("|---|---|---|---:|")
    ultimas: dict[tuple, str] = {}
    for c in contas:
        k = (c["empresa"], "despesas")
        ultimas[k] = max(ultimas.get(k, ""), c["atualizado_em"])
    for n in notas:
        k = (n["empresa"], f"notas {n['tipo_nota']}")
        ultimas[k] = max(ultimas.get(k, ""), n["atualizado_em"])
    for (emp, tipo), quando in sorted(ultimas.items()):
        # O banco grava em UTC; a tela mostra Brasília (UTC-3 fixo).
        dt = datetime.fromisoformat(quando)
        brasilia = dt.astimezone(timezone(timedelta(hours=BRT_OFFSET_H)))
        dias = (hoje - dt).days
        p(f"| {emp} | {tipo} | {brasilia:%d/%m/%Y %H:%M} | {dias} |")
    p(
        "\nNão existe registro de execução de sincronização: a data é o `atualizado_em` "
        "mais recente gravado. Uma sincronização que rodou e não achou nada novo "
        "também atualiza essa coluna (o upsert regrava todas as linhas lidas).\n"
    )

    # ---- 2. Contas sem competência ----------------------------------------
    p("## 2. Contas a pagar sem competência (corrigir no Tiny)\n")
    sem_comp = [c for c in contas if not (c["competencia"] or "").strip()]
    p(
        f"Total: **{len(sem_comp)} contas, {rs(sum(c['valor'] or 0 for c in sem_comp))}**. "
        'Desde a Fase 1 elas aparecem em Despesas com a competência "(vazio)" no funil '
        "(antes sumiam da tela). Não entram em nenhum mês do Dashboard até a competência "
        "ser preenchida no Tiny.\n"
    )
    p("| Empresa | Ano do vencimento | Contas | Valor | Seriam consideradas |")
    p("|---|---|---:|---:|---:|")
    grupos = defaultdict(list)
    for c in sem_comp:
        venc = (c["data_vencimento"] or "")[6:10] or "(sem venc.)"
        grupos[(c["empresa"], venc)].append(c)
    for (emp, ano), linhas in sorted(grupos.items()):
        cons = [x for x in linhas if x["considerar_efetivo"]]
        p(
            f"| {emp} | {ano} | {len(linhas)} | {rs(sum(x['valor'] or 0 for x in linhas))} | "
            f"{len(cons)} ({rs(sum(x['valor'] or 0 for x in cons))}) |"
        )
    cats = defaultdict(Decimal)
    for c in sem_comp:
        if (c["data_vencimento"] or "")[6:10] >= str(ANO_MINIMO):
            cats[c["categoria_primaria"] or "(sem categoria)"] += c["valor"] or 0
    if cats:
        p("\nCom vencimento em 2026 ou depois, por categoria:\n")
        for nome, v in sorted(cats.items(), key=lambda x: -x[1]):
            p(f"- {nome}: {rs(v)}")
    p("")

    # ---- 3. Competências absurdas / futuras --------------------------------
    p("## 3. Competências futuras e absurdas\n")
    fut = defaultdict(lambda: [0, Decimal(0), Decimal(0)])
    tortas = []
    for c in contas_vis:
        am = _ano_mes(c["competencia"])
        if am is None or not 1 <= am[1] <= 12:
            tortas.append(c)
            continue
        if am[0] > 2027:
            g = fut[(c["empresa"], "2028+" if am[0] < 2100 else str(am[0]))]
            g[0] += 1
            g[1] += c["valor"] or 0
            if c["considerar_efetivo"]:
                g[2] += c["valor"] or 0
    p("| Empresa | Faixa | Contas | Valor | Considerado |")
    p("|---|---|---:|---:|---:|")
    for (emp, faixa), (n, v, cons) in sorted(fut.items()):
        p(f"| {emp} | {faixa} | {n} | {rs(v)} | {rs(cons)} |")
    for c in [c for c in contas_vis if (_ano_mes(c["competencia"]) or (0,))[0] >= 2100]:
        p(
            f"\nCompetência absurda: `{c['competencia']}` — {c['empresa']} id {c['id']}, "
            f"venc. {c['data_vencimento']}, {rs(c['valor'])}, categoria "
            f"{c['categoria_primaria']}, considerada = {c['considerar_efetivo']}."
        )
    if tortas:
        p(f"\nCompetência fora do formato MM/AAAA na visão: {len(tortas)} contas.")

    # Quanto da despesa considerada é de competência FUTURA. Desde a Fase 1 o
    # Dashboard sem filtro usa o período padrão (até o último mês com receita)
    # e não soma mais isso; o número fica aqui para dimensionar a sujeira.
    mes_atual = (hoje.year, hoje.month)
    cons_vis = [c for c in contas_vis if c["considerar_efetivo"]]
    total = sum(c["valor"] or 0 for c in cons_vis)
    futuro = sum(
        c["valor"] or 0 for c in cons_vis if (_ano_mes(c["competencia"]) or (0, 0)) > mes_atual
    )
    p(
        f"\nDespesa considerada na visão: {rs(total)}, dos quais "
        f"**{rs(futuro)} ({(futuro / total * 100) if total else 0:.1f}%)** são de competência "
        f"posterior a {hoje:%m/%Y}. O Dashboard sem filtro não soma mais essa parte (período "
        "padrão desde a Fase 1); competência absurda continua a corrigir no Tiny.\n"
    )

    # ---- 4. Sem categoria ---------------------------------------------------
    p("## 4. Contas e notas sem categoria (na visão)\n")
    sc = [c for c in contas_vis if not (c["categoria_primaria"] or "").strip()]
    p(
        f"Contas sem categoria: **{len(sc)}**, {rs(sum(c['valor'] or 0 for c in sc))} "
        f"(consideradas: {rs(sum(c['valor'] or 0 for c in sc if c['considerar_efetivo']))}).\n"
    )
    por = defaultdict(lambda: [0, Decimal(0)])
    for c in sc:
        por[c["empresa"]][0] += 1
        por[c["empresa"]][1] += c["valor"] or 0
    for emp, (n, v) in sorted(por.items()):
        p(f"- {emp}: {n} contas, {rs(v)}")
    p("")
    p("| Empresa | Tipo | Notas sem categoria efetiva | Receita considerada sem categoria |")
    p("|---|---|---:|---:|")
    por_n = defaultdict(lambda: [0, Decimal(0)])
    for n in notas_vis:
        if not (n["categoria_primaria_efetiva"] or "").strip():
            k = (n["empresa"], n["tipo_nota"])
            por_n[k][0] += 1
            if n["considerar_efetivo"]:
                por_n[k][1] += n["valor"] or 0
    for (emp, tipo), (n, v) in sorted(por_n.items()):
        p(f"| {emp} | {tipo} | {n} | {rs(v)} |")
    p(
        "\nNota sem categoria cai no bloco **Sem classificação** do Dashboard: sem imposto "
        "calculado e sem receber rateio, então a receita dela infla o Resultado sem "
        "carregar os 14%/10% de imposto.\n"
    )

    # ---- 5. Notas de serviço sem competência --------------------------------
    p("## 5. Notas na visão sem competência\n")
    sem = [n for n in notas_vis if not (n["competencia_efetiva"] or "").strip()]
    cons = [n for n in sem if n["considerar_efetivo"]]
    p(
        f"{len(sem)} notas ({len(cons)} consideradas, {rs(sum(n['valor'] or 0 for n in cons))}). "
        "Aparecem em Receitas pedindo preenchimento e não entram em nenhum mês do "
        "Dashboard até a competência ser preenchida.\n"
    )
    for n in sem:
        p(
            f"- {n['empresa']} {n['tipo_nota']} nº {n['numero']} emitida {n['data_emissao']}: "
            f"{rs(n['valor'])} ({n['descricao_situacao']})"
        )
    p("")

    # ---- 6. Rateio perdido ---------------------------------------------------
    p("## 6. Adm sem receita para absorver (bloco sem receita no recorte)\n")
    p(
        "`separar()` rateia Adm I/II pela receita de cada categoria do bloco. Quando o "
        "bloco não tem receita no recorte, a cota aparece no Dashboard como a linha "
        "**Adm sem receita para absorver** (desde a Fase 1; antes sumia do custo).\n"
    )
    p("| Recorte | Bloco | Adm I sem base | Adm II sem base |")
    p("|---|---|---:|---:|")
    comps = sorted(
        {
            c["competencia"]
            for c in cons_vis
            if _ano_mes(c["competencia"]) and _ano_mes(c["competencia"]) <= mes_atual
        },
        key=_ano_mes,
    )
    faturadas = [n for n in notas_vis if n["considerar_efetivo"]]
    for emp in (None, "MSV", "START", "GTF"):
        for comp in [None] + comps:
            ns = [
                n
                for n in faturadas
                if (emp is None or n["empresa"] == emp)
                and (comp is None or n["competencia_efetiva"] == comp)
            ]
            cs = [
                c
                for c in cons_vis
                if (emp is None or c["empresa"] == emp)
                and (comp is None or c["competencia"] == comp)
            ]
            b = separar(ns, cs)
            for bloco, r in b["rateio"]["por_bloco"].items():
                if not r["base_receita"] and (r["adm1"] or r["adm2"]):
                    p(
                        f"| {emp or 'Todas'} · {comp or 'sem slicer'} | {bloco} | "
                        f"{rs(r['adm1'])} | {rs(r['adm2'])} |"
                    )
    p("")

    # ---- 7. Outras sujeiras ----------------------------------------------------
    p("## 7. Outras sujeiras encontradas\n")
    grafias = defaultdict(set)
    for c in contas_vis:
        if c["fornecedor"]:
            grafias[c["fornecedor"].strip().casefold()].add(c["fornecedor"])
    dup = {k: v for k, v in grafias.items() if len(v) > 1}
    p(
        f"- Fornecedores com a mesma grafia mudando só a caixa/espaço: **{len(dup)}** "
        "(ex.: `Fulano` e `FULANO`). Aparecem duas vezes no funil e somam separados na "
        "árvore do Dashboard. Também deixam a ordem do funil **não determinística** "
        "(achado do golden master)."
    )
    cats = defaultdict(set)
    for c in contas_vis:
        if c["categoria_primaria"]:
            cats[c["categoria_primaria"].strip().upper()].add(c["categoria_primaria"])
    dupc = {k: sorted(v) for k, v in cats.items() if len(v) > 1}
    p(
        f"- Categorias primárias com grafia divergente só na caixa/espaço: {dupc or 'nenhuma'}. "
        "A regra de exclusão compara texto exato; a classificação Vendas/Serviços ignora caixa."
    )
    situ = sorted({n["descricao_situacao"] or "(vazio)" for n in notas_vis})
    p(
        f"- Situações de nota na visão: {', '.join(situ)}. A lista de exclusão tem "
        '`EXCLUIDA` sem acento — uma nota "Excluída" entraria como receita.'
    )
    sem_valor_c = sum(1 for c in contas_vis if c["valor"] is None)
    sem_valor_n = sum(1 for n in notas_vis if n["valor"] is None)
    p(f"- Linhas sem valor na visão: {sem_valor_c} contas, {sem_valor_n} notas.")
    p(f"- Regras de exclusão ativas: {dict(regras)}.")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório de qualidade de dados (só leitura)")
    ap.add_argument("--db", default=str(RAIZ / "data" / "app.db"))
    ap.add_argument("--saida", help="grava em arquivo (ex.: relatorios/qualidade.md)")
    args = ap.parse_args()
    texto = relatorio(Path(args.db), datetime.now(timezone.utc))
    if args.saida:
        Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(args.saida).write_text(texto, encoding="utf-8")
        print(f"Relatório gravado em {args.saida}")
    else:
        sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
