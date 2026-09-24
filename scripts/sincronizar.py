"""
Sincroniza o banco local com o Tiny pela linha de comando.

Faz o mesmo que os botões da tela "Sincronizar com o Tiny", mas sem depender do
servidor web ficar de pé — útil para a carga inicial (que demora) e para agendar
no futuro.

Uso:
    python scripts/sincronizar.py MSV             # empresa obrigatória, ano atual
    python scripts/sincronizar.py MSV 2026        # empresa e ano
    python scripts/sincronizar.py MSV 2026 --forcar   # rebusca tudo (pega mudança de competência)
    python scripts/sincronizar.py TODAS 2026      # todas as empresas, uma após a outra

    # período livre em vez de ano (para carga histórica completa):
    python scripts/sincronizar.py START --desde 2015-01-01 --ate 2035-12-31

    # escolher por qual data filtrar (padrão: as duas)
    python scripts/sincronizar.py START --desde 2025-01-01 --por emissao

A empresa é obrigatória de propósito: sincronizar "todas" sem querer pode
disparar horas de trabalho, porque cada empresa tem seu próprio volume.
"""
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config.companies import load_companies
from app.db import init_db
from app.sincronizacao import sincronizar
from app.tiny_client.api_client import TinyAPIClient, TinyAPIError
from app.trava import SincronizacaoEmAndamento


def opcao(nome: str, padrao=None):
    """Lê --nome valor da linha de comando."""
    marca = f"--{nome}"
    if marca in sys.argv:
        i = sys.argv.index(marca)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return padrao


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    forcar = "--forcar" in sys.argv

    todas = load_companies()
    if not todas:
        print("Nenhuma empresa configurada no .env ainda.")
        return

    disponiveis = ", ".join(e.nome for e in todas)
    if not argumentos:
        print("Informe a empresa. Exemplo:\n")
        print(f"    python scripts/sincronizar.py {todas[0].nome} 2026\n")
        print(f"Empresas configuradas: {disponiveis}")
        print("Use TODAS para sincronizar todas (pode levar horas).")
        return

    alvo = argumentos[0]

    desde, ate = opcao("desde"), opcao("ate")
    por_texto = (opcao("por") or "ambos").lower()
    por = {"emissao": ("emissao",), "vencimento": ("vencimento",),
           "ambos": ("emissao", "vencimento")}.get(por_texto)
    if por is None:
        print(f"--por inválido: {por_texto}. Use emissao, vencimento ou ambos.")
        return

    periodo = None
    ano = None
    if desde or ate:
        periodo = (
            date.fromisoformat(desde) if desde else date(2000, 1, 1),
            date.fromisoformat(ate) if ate else date(2035, 12, 31),
        )
    else:
        ano = int(argumentos[1]) if len(argumentos) > 1 else date.today().year

    if alvo.upper() == "TODAS":
        empresas = todas
    else:
        empresas = [e for e in todas if e.nome.upper() == alvo.upper() or e.key.upper() == alvo.upper()]
        if not empresas:
            print(f"Empresa '{alvo}' não encontrada. Configuradas: {disponiveis}")
            return

    init_db()
    modo = "FORÇADO (rebusca tudo)" if forcar else "normal (só novas e alteradas)"
    alcance = (f"{periodo[0]} a {periodo[1]}" if periodo else str(ano))
    print(f"Sincronizando {alcance} — filtro por {por_texto} — modo {modo}\n")

    for empresa in empresas:
        print(f"=== {empresa.nome} ===")
        if not empresa.has_api_token:
            print("  sem token de API no .env — pulando.\n")
            continue

        cliente = TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)
        if not cliente.testar_conexao():
            print("  não consegui conectar (token inválido ou sem internet) — pulando.\n")
            continue

        ultimo = {"marco": -1}

        def progresso(feitos, total, etapa, ultimo=ultimo):
            if total and feitos:
                pct = int(100 * feitos / total)
                if pct // 5 != ultimo["marco"]:
                    ultimo["marco"] = pct // 5
                    agora = datetime.now().strftime("%H:%M:%S")
                    print(f"  [{agora}] {feitos}/{total} ({pct}%) — {etapa}")
            elif total:
                print(f"  {total} contas encontradas... — {etapa}", end="\r")

        try:
            resumo = sincronizar(cliente, empresa.nome, ano, forcar=forcar,
                                 progresso=progresso, periodo=periodo, por=por)
        except SincronizacaoEmAndamento as e:
            print(f"  {e}")
            print("  (rodar duas ao mesmo tempo faz as duas ficarem lentas por rate limit)\n")
            return
        except TinyAPIError as e:
            print(f"  ERRO: {e}\n")
            continue

        print(f"\n  encontradas no período : {resumo['encontradas']}")
        print(f"  novas gravadas         : {resumo['novas']}")
        print(f"  atualizadas            : {resumo['atualizadas']}")
        print(f"  sem mudança            : {resumo['sem_mudanca']}")

        if resumo["mudancas"]:
            print("\n  o que mudou no ERP:")
            for m in resumo["mudancas"]:
                difs = "; ".join(
                    f"{d['campo']}: {d['de']} -> {d['para']}" for d in m["diferencas"]
                )
                print(f"    - {m['fornecedor']}: {difs}")
            if resumo.get("mudancas_total", 0) > len(resumo["mudancas"]):
                print(f"    (mostrando {len(resumo['mudancas'])} de {resumo['mudancas_total']})")
        print()


if __name__ == "__main__":
    main()
