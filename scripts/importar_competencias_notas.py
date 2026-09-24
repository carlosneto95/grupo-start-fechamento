"""
Aplica uma planilha de correção de competência sobre as notas fiscais.

A competência de uma nota de serviço quase nunca é o mês da emissão — o serviço
é prestado num mês e faturado em outro. O Tiny não guarda esse dado, então ele
vem de fora, numa planilha montada à mão.

O valor vai para `competencia_manual`, NUNCA para `competencia`. As duas colunas
existem justamente para isso: `competencia` é o que o sistema derivou da emissão
e fica preservada ao lado, e o ajuste manual tem precedência na tela. Assim a
correção sobrevive à próxima sincronização e continua sendo possível ver o que
o ERP dizia.

Colunas esperadas: Competência, Empresa, Numero NF, Data Emissão, Cliente, Valor
A competência vem por extenso ("DEZEMBRO/25") e é convertida para "MM/AAAA".

Uso:
    python scripts/importar_competencias_notas.py "arquivo.xlsx" --tipo servico
    python scripts/importar_competencias_notas.py "arquivo.xlsx" --tipo servico --simular
"""
import sys
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.db import get_conn, init_db

MESES = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
    "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}

COLUNAS_ESPERADAS = ["Competência", "Empresa", "Numero NF"]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def competencia_mm_aaaa(bruto) -> str | None:
    """"DEZEMBRO/25" -> "12/2025". Aceita também "12/2025" já pronto.

    Devolve None quando não reconhece — a linha é reportada e ignorada, nunca
    chutada: competência errada é pior que competência faltando, porque some
    dentro do total sem ninguém perceber."""
    texto = str(bruto or "").strip().upper()
    if not texto:
        return None
    nome, _, ano = texto.partition("/")
    if not ano.isdigit():
        return None
    ano = f"20{ano}" if len(ano) == 2 else ano
    if len(ano) != 4:
        return None
    if nome.isdigit():                      # já veio "MM/AAAA"
        mes = int(nome)
        return f"{mes:02d}/{ano}" if 1 <= mes <= 12 else None
    mes = MESES.get(_sem_acento(nome))
    return f"{mes:02d}/{ano}" if mes else None


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    simular = "--simular" in sys.argv
    tipo = "servico"
    if "--tipo" in sys.argv:
        i = sys.argv.index("--tipo")
        if i + 1 < len(sys.argv):
            tipo = sys.argv[i + 1]

    if not argumentos:
        print(__doc__)
        return

    caminho = Path(argumentos[0])
    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}")
        return

    df = pd.read_excel(caminho)
    faltando = [c for c in COLUNAS_ESPERADAS if c not in df.columns]
    if faltando:
        print(f"Faltam colunas na planilha: {faltando}")
        return

    df["__comp"] = df["Competência"].map(competencia_mm_aaaa)
    df["__nf"] = df["Numero NF"].astype(str).str.strip()
    df["__emissao"] = pd.to_datetime(df.get("Data Emissão"), errors="coerce",
                                     dayfirst=True).dt.strftime("%d/%m/%Y")
    df["__valor"] = pd.to_numeric(df.get("Valor"), errors="coerce")
    df["__empresa"] = df["Empresa"].astype(str).str.strip()

    invalidas = df[df["__comp"].isna()]
    if len(invalidas):
        print(f"{len(invalidas)} linha(s) com competência ilegível — ignoradas:")
        for _, r in invalidas.head(10).iterrows():
            print(f"   NF {r['__nf']}: {r['Competência']!r}")
    df = df[df["__comp"].notna()]

    init_db()
    conn = get_conn()
    try:
        # Notas agrupadas por (empresa, numero). Agrupar é necessário porque o
        # número da NF NÃO é chave: a GTF reaproveita numeração — existem duas
        # NF 45, uma de fevereiro e outra de agosto — e casar só pelo número
        # escolheria uma das duas na sorte.
        banco: dict[tuple[str, str], list[dict]] = {}
        for r in conn.execute(
            "SELECT id, empresa, numero, data_emissao, valor, competencia, "
            "competencia_manual FROM notas WHERE tipo_nota = ?", (tipo,)
        ):
            banco.setdefault((r["empresa"], str(r["numero"])), []).append(dict(r))

        aplicar = []                      # [(id, competencia)]
        mudancas, ausentes = [], []
        conflitos, repartidas, sem_par = [], [], []
        iguais = 0

        for (empresa, nf), grupo in df.groupby(["__empresa", "__nf"]):
            candidatos = banco.get((empresa, nf), [])
            registros = grupo.to_dict("records")

            if not candidatos:
                ausentes.append((empresa, nf))
                continue

            if len(registros) == 1 and len(candidatos) == 1:
                pares = [(candidatos[0], registros[0])]
            else:
                # Casa cada linha com a nota de mesma emissão E mesmo valor —
                # é o que separa duas notas que dividem o número.
                pares, sobrando, livres = [], [], list(candidatos)
                for reg in registros:
                    achou = next(
                        (c for c in livres
                         if c["data_emissao"] == reg["__emissao"]
                         and reg["__valor"] is not None and c["valor"] is not None
                         and abs(float(c["valor"]) - float(reg["__valor"])) < 0.01),
                        None,
                    )
                    if achou:
                        livres.remove(achou)
                        pares.append((achou, reg))
                    else:
                        sobrando.append(reg)

                if sobrando:
                    comps = {r["__comp"] for r in sobrando}
                    soma = sum(float(r["__valor"] or 0) for r in sobrando)
                    unica = candidatos[0] if len(candidatos) == 1 else None
                    # Várias linhas cujos valores SOMAM o valor da nota: a nota
                    # cobre mais de uma competência. O sistema guarda uma
                    # competência por nota, então isso não tem como ser gravado.
                    # Reporta e não chuta — meia nota no mês errado é pior que
                    # nota inteira no mês antigo, porque ninguém percebe.
                    if (unica is not None and not pares and len(comps) > 1
                            and abs(soma - float(unica["valor"] or 0)) < 0.01):
                        repartidas.append((empresa, nf, unica["valor"],
                                           [(r["__comp"], r["__valor"]) for r in sobrando]))
                        continue
                    if unica is not None and not pares and len(comps) == 1:
                        pares = [(unica, sobrando[0])]      # mesma competência repetida
                    elif len(comps) > 1:
                        conflitos.append((empresa, nf, sorted(comps)))
                        continue
                    else:
                        sem_par.extend((empresa, nf, r["__emissao"], r["__valor"])
                                       for r in sobrando)
                        continue

            for nota, reg in pares:
                vigente = nota["competencia_manual"] or nota["competencia"]
                if vigente == reg["__comp"]:
                    iguais += 1
                    continue
                aplicar.append((nota["id"], reg["__comp"]))
                mudancas.append((empresa, nf, vigente, reg["__comp"], nota["valor"]))

        if not simular:
            for id_nota, comp in aplicar:
                conn.execute(
                    "UPDATE notas SET competencia_manual=? WHERE id=? AND tipo_nota=?",
                    (comp, id_nota, tipo),
                )
            conn.commit()
    finally:
        conn.close()

    rotulo = "seriam alteradas" if simular else "alteradas"
    print()
    print(f"já corretas         : {iguais}")
    print(f"{rotulo:<20}: {len(aplicar)}")
    print(f"não achadas no banco: {len(ausentes)}")
    for e, nf in ausentes[:10]:
        print(f"   {e}/NF {nf}")

    if repartidas:
        total = sum(float(v or 0) for _, _, v, _ in repartidas)
        print()
        print(f"{len(repartidas)} nota(s) ABRANGEM MAIS DE UMA COMPETÊNCIA — "
              f"não aplicadas (R$ {total:,.2f}):")
        for empresa, nf, valor, partes in repartidas:
            detalhe = " + ".join(f"{c} R$ {v:,.2f}" for c, v in partes)
            print(f"   {empresa}/NF {nf}: nota de R$ {valor:,.2f} = {detalhe}")
        print("   (uma competência por nota; escolha uma delas ou parta a nota no Tiny)")

    if conflitos:
        print()
        print(f"{len(conflitos)} NF(s) com competências CONFLITANTES — não aplicadas:")
        for empresa, nf, comps in conflitos:
            print(f"   {empresa}/NF {nf}: {' vs '.join(comps)}")

    if sem_par:
        print()
        print(f"{len(sem_par)} linha(s) sem nota correspondente (emissão/valor não batem):")
        for empresa, nf, emissao, valor in sem_par[:10]:
            print(f"   {empresa}/NF {nf} emissão {emissao} R$ {valor:,.2f}")

    from app.visao import ANO_MINIMO
    saem = [m for m in mudancas if m[3][3:] < str(ANO_MINIMO)]
    if saem:
        total = sum(m[4] or 0 for m in saem)
        print()
        print(f"ATENÇÃO: {len(saem)} nota(s) passam a ter competência anterior a "
              f"{ANO_MINIMO} e SAEM da visão do sistema (R$ {total:,.2f}):")
        for empresa, nf, de, para, valor in sorted(saem, key=lambda m: -(m[4] or 0)):
            print(f"   {empresa}/NF {nf:>5}  {de} -> {para}   R$ {valor:>13,.2f}")

    if simular:
        print("\nSIMULAÇÃO — nada foi gravado.")


if __name__ == "__main__":
    main()
