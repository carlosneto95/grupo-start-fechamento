"""
Sincroniza o banco com o Tiny pela linha de comando — o MESMO job da tela e
da tarefa agendada (app/sincronizar_tudo.py): despesas e notas, com histórico
gravado em `sincronizacoes`.

Uso:
    python scripts/sincronizar.py MSV                 # empresa, ano atual, contas e notas
    python scripts/sincronizar.py MSV 2026
    python scripts/sincronizar.py TODAS 2026          # as três, uma após a outra
    python scripts/sincronizar.py MSV 2026 --forcar   # rebusca tudo (pega mudança de competência)
    python scripts/sincronizar.py MSV 2026 --so notas # só receitas (ou --so contas)

    # período livre em vez de ano (carga histórica):
    python scripts/sincronizar.py START --desde 2015-01-01 --ate 2035-12-31

    # por qual data filtrar as CONTAS (padrão: as duas)
    python scripts/sincronizar.py START --desde 2025-01-01 --por emissao

A empresa é obrigatória de propósito: "todas" sem querer pode disparar horas
de trabalho, porque cada empresa tem seu próprio volume.
"""

import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import sincronizar_tudo  # noqa: E402
from app.config.companies import load_companies  # noqa: E402
from app.db import init_db  # noqa: E402
from app.sincronizacao import periodo_do_ano  # noqa: E402

POR = {"emissao": ("emissao",), "vencimento": ("vencimento",), "ambos": ("emissao", "vencimento")}
SO = {"contas": ("contas",), "notas": ("notas",), None: sincronizar_tudo.TIPOS}


def opcao(nome: str, padrao=None):
    """Lê --nome valor da linha de comando."""
    marca = f"--{nome}"
    if marca in sys.argv:
        i = sys.argv.index(marca)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return padrao


def escolher_empresas(alvo: str, todas):
    if alvo.upper() == "TODAS":
        return todas
    return [e for e in todas if alvo.upper() in (e.nome.upper(), e.key.upper())]


def imprimir_progresso():
    """Imprime a cada 5% por (empresa, tipo), sem inundar o terminal."""
    marcos: dict = {}

    def progresso(empresa, tipo, feitos, total, etapa):
        if not (total and feitos):
            return
        pct = int(100 * feitos / total)
        if pct // 5 != marcos.get((empresa, tipo)):
            marcos[(empresa, tipo)] = pct // 5
            print(
                f"  [{datetime.now():%H:%M:%S}] {empresa}/{tipo} {feitos}/{total} ({pct}%) — {etapa}"
            )

    return progresso


def main(origem: str = "cli") -> int:
    # Posicionais: tudo que não é "--opção" nem o VALOR de uma opção (--desde X).
    posicoes_de_valor = {
        i + 1 for i, a in enumerate(sys.argv) if a in ("--desde", "--ate", "--por", "--so")
    }
    argumentos = [
        a
        for i, a in enumerate(sys.argv)
        if i > 0 and not a.startswith("--") and i not in posicoes_de_valor
    ]

    todas = load_companies()
    if not todas:
        print("Nenhuma empresa configurada no .env.")
        return 1
    if not argumentos:
        print(__doc__)
        print("Empresas configuradas:", ", ".join(e.nome for e in todas), "(ou TODAS)")
        return 1

    empresas = escolher_empresas(argumentos[0], todas)
    if not empresas:
        print(f"Empresa '{argumentos[0]}' não encontrada.")
        return 1

    por = POR.get((opcao("por") or "ambos").lower())
    tipos = SO.get(opcao("so"))
    if por is None or tipos is None:
        print("--por aceita emissao|vencimento|ambos; --so aceita contas|notas.")
        return 1

    desde, ate = opcao("desde"), opcao("ate")
    if desde or ate:
        periodo = (
            date.fromisoformat(desde) if desde else date(2000, 1, 1),
            date.fromisoformat(ate) if ate else date(2035, 12, 31),
        )
    else:
        ano = int(argumentos[1]) if len(argumentos) > 1 else date.today().year
        periodo = periodo_do_ano(ano)

    init_db()
    pedido = sincronizar_tudo.Pedido(
        empresas=empresas,
        periodo=periodo,
        origem=origem,
        tipos=tipos,
        forcar="--forcar" in sys.argv,
        por=por,
    )
    modo = "FORÇADO (rebusca tudo)" if pedido.forcar else "normal (só novas e alteradas)"
    print(f"Sincronizando {periodo[0]} a {periodo[1]} — {', '.join(tipos)} — modo {modo}\n")

    resultados = sincronizar_tudo.executar(pedido, progresso=imprimir_progresso())

    print()
    for r in resultados:
        if r.status == "ok":
            print(
                f"{r.empresa}/{r.tipo}: {r.resumo.get('encontradas')} no período, "
                f"{r.resumo.get('novas')} novas, {r.resumo.get('atualizadas')} atualizadas"
            )
        else:
            print(f"{r.empresa}/{r.tipo}: ERRO — {r.erro}")
    # Código de saída 1 se qualquer parte falhou: a tarefa agendada precisa enxergar.
    return 0 if all(r.status == "ok" for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
