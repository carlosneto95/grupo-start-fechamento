"""Job ÚNICO de sincronização com o Tiny: contas a pagar e notas, das três
empresas. É o mesmo código chamado pela tela (origem "tela"), pela linha de
comando ("cli") e pela tarefa agendada ("agendada").

Antes da Fase 1 havia dois caminhos: a tela sincronizava só despesas, e as
receitas dependiam de um script de terminal. Resultado: receita parada
enquanto a despesa andava, e o dashboard de agosto com metade da receita.

Cada execução grava uma linha por (empresa × tipo) em `sincronizacoes`, com
início, fim, contagens e erro — é o que responde "quando foi a última
sincronização que deu certo", em vez de adivinhar pelo `atualizado_em`.

Uma falha numa empresa NÃO derruba as outras: o erro é registrado e o job
segue. A trava é por empresa e cobre contas E notas, porque as duas usam a
mesma cota de chamadas por minuto da conta no Tiny.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from app import receitas, sincronizacao
from app.config.companies import CompanyConfig
from app.db import agora_brasilia, get_conn
from app.registro import mascarar
from app.trava import SincronizacaoEmAndamento, adquirir

log = logging.getLogger("app.sincronizacao")

TIPOS = ("contas", "notas")
ORIGENS = ("tela", "cli", "agendada")


@dataclass
class Pedido:
    empresas: list[CompanyConfig]
    periodo: tuple[date, date]
    origem: str
    tipos: tuple[str, ...] = TIPOS
    forcar: bool = False
    # Por quais datas filtrar as CONTAS (as notas filtram pela emissão).
    por: tuple[str, ...] = ("emissao", "vencimento")

    def __post_init__(self):
        if self.origem not in ORIGENS:
            raise ValueError(f"origem inválida: {self.origem}")
        if not self.tipos or any(t not in TIPOS for t in self.tipos):
            raise ValueError(f"tipos inválidos: {self.tipos}")


@dataclass
class Resultado:
    empresa: str
    tipo: str
    status: str  # "ok" | "erro"
    resumo: dict = field(default_factory=dict)
    erro: str | None = None


def _abrir_registro(lote: str, pedido: Pedido, empresa: str, tipo: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO sincronizacoes (lote, origem, empresa, tipo, periodo_inicio,"
            " periodo_fim, forcado, iniciada_em, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'rodando')",
            (
                lote,
                pedido.origem,
                empresa,
                tipo,
                pedido.periodo[0].isoformat(),
                pedido.periodo[1].isoformat(),
                int(pedido.forcar),
                agora_brasilia(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _fechar_registro(id_: int, resultado: Resultado) -> None:
    r = resultado.resumo
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE sincronizacoes SET terminada_em = ?, status = ?, encontradas = ?,"
            " novas = ?, atualizadas = ?, erro = ? WHERE id = ?",
            (
                agora_brasilia(),
                resultado.status,
                r.get("encontradas"),
                r.get("novas"),
                r.get("atualizadas"),
                resultado.erro,
                id_,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _texto_erro(e: Exception) -> str:
    """Mensagem para o banco e para a tela: tipo + texto, MASCARADO (a URL da
    API do Tiny carrega o token) e curto."""
    return mascarar(f"{type(e).__name__}: {e}")[:500]


def _cliente_padrao(empresa: CompanyConfig):
    from app.tiny_client.api_client import TinyAPIClient

    return TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)


def executar(pedido: Pedido, progresso=None, fabrica_cliente=_cliente_padrao) -> list[Resultado]:
    """Roda o pedido e devolve um Resultado por (empresa × tipo).

    `progresso(empresa, tipo, feitos, total, etapa)` é chamado durante o
    trabalho (a tela usa para a barra; a linha de comando, para imprimir).
    `fabrica_cliente` existe para os testes trocarem a API por uma falsa."""
    lote = uuid.uuid4().hex
    resultados: list[Resultado] = []

    for empresa in pedido.empresas:
        registros = {t: _abrir_registro(lote, pedido, empresa.nome, t) for t in pedido.tipos}

        def falhar_todos(mensagem: str, pendentes: list[str]) -> None:
            for tipo in pendentes:
                r = Resultado(empresa.nome, tipo, "erro", erro=mensagem)
                _fechar_registro(registros[tipo], r)
                resultados.append(r)

        if not empresa.has_api_token:
            falhar_todos("sem token de API no .env", list(pedido.tipos))
            continue

        try:
            with adquirir(empresa.nome):
                cliente = fabrica_cliente(empresa)
                if not cliente.testar_conexao():
                    falhar_todos(
                        "não conectou na API (token inválido ou sem internet)", list(pedido.tipos)
                    )
                    continue
                for tipo in pedido.tipos:
                    resultados.append(
                        _um_tipo(cliente, empresa.nome, tipo, pedido, registros[tipo], progresso)
                    )
        except SincronizacaoEmAndamento as e:
            ja = {(r.empresa, r.tipo) for r in resultados}
            falhar_todos(str(e), [t for t in pedido.tipos if (empresa.nome, t) not in ja])
        except Exception as e:  # erro fora de um tipo (ex.: ao conectar)
            log.exception("Sincronização de %s falhou", empresa.nome)
            ja = {(r.empresa, r.tipo) for r in resultados}
            falhar_todos(_texto_erro(e), [t for t in pedido.tipos if (empresa.nome, t) not in ja])

    return resultados


def _um_tipo(cliente, empresa: str, tipo: str, pedido: Pedido, id_registro: int, progresso):
    def avisar(feitos, total, etapa):
        if progresso:
            progresso(empresa, tipo, feitos, total, etapa)

    try:
        if tipo == "contas":
            # A trava já está com este job: chama o miolo sem pegá-la de novo.
            resumo = sincronizacao._sincronizar(
                cliente, empresa, pedido.periodo, pedido.forcar, avisar, pedido.por
            )
        else:
            resumo = receitas.sincronizar_notas(
                cliente, empresa, pedido.periodo[0], pedido.periodo[1], avisar
            )
        resultado = Resultado(empresa, tipo, "ok", resumo=resumo)
    except Exception as e:
        log.exception("Sincronização de %s/%s falhou", empresa, tipo)
        resultado = Resultado(empresa, tipo, "erro", erro=_texto_erro(e))
    _fechar_registro(id_registro, resultado)
    return resultado


def ultimas() -> list[dict]:
    """Por empresa e tipo: a última execução (qualquer status) e a última que
    DEU CERTO. É o que a tela de Sincronizar e o futuro painel de pendências
    mostram."""
    conn = get_conn()
    try:
        linhas = conn.execute(
            """
            SELECT empresa, tipo,
                   MAX(iniciada_em) AS ultima_execucao,
                   MAX(CASE WHEN status = 'ok' THEN terminada_em END) AS ultimo_sucesso,
                   (SELECT s2.status FROM sincronizacoes s2
                     WHERE s2.empresa = s.empresa AND s2.tipo = s.tipo
                     ORDER BY s2.iniciada_em DESC, s2.id DESC LIMIT 1) AS ultimo_status,
                   (SELECT s2.erro FROM sincronizacoes s2
                     WHERE s2.empresa = s.empresa AND s2.tipo = s.tipo
                     ORDER BY s2.iniciada_em DESC, s2.id DESC LIMIT 1) AS ultimo_erro
            FROM sincronizacoes s
            GROUP BY empresa, tipo
            ORDER BY empresa, tipo
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in linhas]
