"""
Tarefa diária (agendada no PythonAnywhere na Fase 5; roda igual no Windows):

    1. backup verificado do banco (retenção de 30 dias);
    2. sincronização das três empresas, despesas e notas, ano corrente —
       o mesmo job da tela, com origem "agendada";
    3. relatório de qualidade de dados em relatorios/qualidade_AAAA-MM-DD.md.

    .venv\Scripts\python scripts\tarefa_diaria.py

Sai com código 1 se a sincronização de qualquer empresa falhar: o agendador
do PythonAnywhere mostra a execução como falha e o log diz qual.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import db, sincronizar_tudo  # noqa: E402
from app.config.companies import load_companies  # noqa: E402
from app.sincronizacao import periodo_do_ano  # noqa: E402

RETENCAO_DIAS = 30


def limpar_backups_antigos(pasta: Path) -> int:
    """Apaga os backups DIÁRIOS com mais de 30 dias. Os de migração e de
    importação ficam: são o ponto de volta de uma mudança de esquema."""
    limite = datetime.now() - timedelta(days=RETENCAO_DIAS)
    apagados = 0
    for arquivo in pasta.glob("*_diario.db"):
        if datetime.fromtimestamp(arquivo.stat().st_mtime) < limite:
            arquivo.unlink()
            apagados += 1
    return apagados


def main() -> int:
    db.init_db()  # banco do .env (GSF_BANCO) + migrações pendentes
    print(f"[{datetime.now():%H:%M:%S}] backup:", db.fazer_backup(Path(db.DB_PATH), "diario"))
    print(
        f"[{datetime.now():%H:%M:%S}] backups antigos apagados:",
        limpar_backups_antigos(db.PASTA_BACKUPS),
    )

    empresas = [e for e in load_companies() if e.has_api_token]
    pedido = sincronizar_tudo.Pedido(
        empresas=empresas, periodo=periodo_do_ano(date.today().year), origem="agendada"
    )
    resultados = sincronizar_tudo.executar(pedido)
    for r in resultados:
        situacao = "ok" if r.status == "ok" else f"ERRO — {r.erro}"
        print(f"[{datetime.now():%H:%M:%S}] {r.empresa}/{r.tipo}: {situacao}")

    from scripts.relatorio_qualidade import relatorio

    destino = RAIZ / "relatorios" / f"qualidade_{date.today().isoformat()}.md"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(relatorio(Path(db.DB_PATH), datetime.now(timezone.utc)), encoding="utf-8")
    print(f"[{datetime.now():%H:%M:%S}] relatório:", destino)
    return 0 if all(r.status == "ok" for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
