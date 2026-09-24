"""Pendências de dados, ao vivo (Fase 4.1).

É o relatório de qualidade da Fase 0 dentro do sistema: cada pendência tem
contagem por empresa e um LINK para as linhas, montado com os filtros de
coluna que as telas já entendem (ex.: /despesas?competencia=(vazio)). Nada é
corrigido aqui — o sistema é espelho do Tiny; a correção se faz lá.

Tudo respeita o escopo: quem só vê a MSV só vê as pendências da MSV.

O selo "sincronizado há N dias" (topo de todas as telas) também mora aqui: ele
teria evitado o dashboard de agosto com metade da receita.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from app.db import FUSO_BRASILIA, get_conn
from app.dinheiro import ZERO
from app.escopo import clausula
from app.receitas import listar_notas
from app.repositorio_contas_pagar import listar_contas
from app.visao import SEM_VALOR

# Selo fica vermelho acima deste número de dias sem sincronizar com sucesso.
DIAS_ALERTA_SINCRONIZACAO = 2
# Competência além deste horizonte é tratada como digitação errada (ex.: 07/2800).
# Parcelas de financiamento legítimas vão, no banco atual, até 2032.
ANOS_HORIZONTE = 10


@dataclass
class Pendencia:
    chave: str
    titulo: str
    explicacao: str
    onde_corrigir: str
    # empresa -> [quantidade, valor]
    por_empresa: dict = field(default_factory=lambda: defaultdict(lambda: [0, ZERO]))
    # Endpoint + filtros para ver as linhas. O template monta a URL com
    # url_for: caminho fixo quebraria sob o prefixo de produção.
    rota: str = ""
    filtros: dict = field(default_factory=dict)
    exemplos: list = field(default_factory=list)

    def somar(self, empresa: str, valor) -> None:
        linha = self.por_empresa[empresa]
        linha[0] += 1
        linha[1] += valor or ZERO

    @property
    def quantidade(self) -> int:
        return sum(q for q, _ in self.por_empresa.values())

    @property
    def valor(self):
        return sum((v for _, v in self.por_empresa.values()), ZERO)

    def parametros(self, empresa: str | None = None) -> dict:
        """Filtros da URL (para url_for); com empresa, só as linhas dela."""
        filtros = dict(self.filtros)
        if empresa:
            filtros["empresa"] = empresa
        return filtros


def _competencia_absurda(comp: str, ano_limite: int) -> bool:
    comp = (comp or "").strip()
    if not comp:
        return False
    mes, _, ano = comp.partition("/")
    if not (mes.isdigit() and ano.isdigit() and len(ano) == 4):
        return True
    return not 1 <= int(mes) <= 12 or int(ano) > ano_limite


def calcular(escopo, hoje: date | None = None) -> list[Pendencia]:
    """Todas as pendências dentro do escopo, na ordem em que aparecem na tela."""
    hoje = hoje or datetime.now(FUSO_BRASILIA).date()
    ano_limite = hoje.year + ANOS_HORIZONTE

    sem_comp = Pendencia(
        "contas_sem_competencia",
        "Contas a pagar sem competência",
        "Aparecem em Despesas, mas não entram em nenhum mês do Dashboard.",
        "Tiny: preencher a competência da conta.",
        rota="despesas.listar",
        filtros={"competencia": SEM_VALOR},
    )
    absurda = Pendencia(
        "contas_competencia_absurda",
        "Contas com competência fora do padrão",
        f"Mês fora de 01–12, formato inválido ou ano depois de {ano_limite}.",
        "Tiny: corrigir a competência da conta.",
        rota="despesas.listar",
    )
    sem_cat_conta = Pendencia(
        "contas_sem_categoria",
        "Contas a pagar sem categoria",
        "Caem no bloco Sem classificação do Dashboard: sem centro de custo nem rateio.",
        "Tiny: classificar a conta.",
        rota="despesas.listar",
        filtros={"categoria_primaria": SEM_VALOR},
    )
    sem_comp_nota = Pendencia(
        "notas_sem_competencia",
        "Notas de serviço sem competência",
        "O Tiny não informa a competência da NFS-e pela API: sem ela, a receita "
        "não entra em nenhum mês do Dashboard.",
        "Sistema: tela Receitas Serviços, clicar na competência e preencher.",
        rota="receitas.servicos",
        filtros={"competencia_efetiva": SEM_VALOR, "considerar_efetivo": "Considerar"},
    )
    sem_cat_nota = Pendencia(
        "notas_sem_categoria",
        "Notas consideradas como receita sem categoria",
        "Caem no bloco Sem classificação: sem os 14%/10% de imposto nem rateio. "
        "Inclui nota de retorno ou devolução que talvez nem seja receita.",
        "Sistema: definir a categoria ou marcar Desconsiderar; ou marcador no Tiny.",
        rota="receitas.vendas",
        filtros={"categoria_primaria_efetiva": SEM_VALOR, "considerar_efetivo": "Considerar"},
    )
    grafia = Pendencia(
        "fornecedores_grafia",
        "Fornecedores com a mesma grafia mudando só maiúsculas",
        "Aparecem duas vezes no funil e somam separados na árvore de gastos.",
        "Tiny: unificar o cadastro do fornecedor.",
        rota="despesas.listar",
    )

    competencias_absurdas: set[str] = set()
    grafias: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in listar_contas(escopo, ordenado=False):
        comp = (c["competencia"] or "").strip()
        if not comp:
            sem_comp.somar(c["empresa"], c["valor"])
        elif _competencia_absurda(comp, ano_limite):
            absurda.somar(c["empresa"], c["valor"])
            competencias_absurdas.add(comp)
        if not (c["categoria_primaria"] or "").strip():
            sem_cat_conta.somar(c["empresa"], c["valor"])
        if c["fornecedor"]:
            grafias[(c["empresa"], c["fornecedor"].strip().casefold())].add(c["fornecedor"])
    absurda.filtros = {"competencia": sorted(competencias_absurdas)}

    # Uma "ocorrência" por grupo de grafias (não por conta): é o cadastro que
    # precisa ser unificado. Exemplos levam link filtrando as grafias juntas.
    for (empresa, _), nomes in sorted(grafias.items()):
        if len(nomes) > 1:
            grafia.somar(empresa, ZERO)
            if len(grafia.exemplos) < 10:
                grafia.exemplos.append(
                    (" × ".join(sorted(nomes)), {"empresa": empresa, "fornecedor": sorted(nomes)})
                )

    for n in listar_notas(escopo, ordenado=False):
        if not n["considerar_efetivo"]:
            continue
        if n["tipo_nota"] == "servico" and not (n["competencia_efetiva"] or "").strip():
            sem_comp_nota.somar(n["empresa"], n["valor"])
        if n["tipo_nota"] == "venda" and not (n["categoria_primaria_efetiva"] or "").strip():
            sem_cat_nota.somar(n["empresa"], n["valor"])

    return [sem_comp_nota, sem_cat_nota, sem_comp, sem_cat_conta, absurda, grafia]


# ---- selo de sincronização ------------------------------------------------------------


@dataclass
class SeloSincronizacao:
    dias: int | None  # None = nunca sincronizou com sucesso
    detalhe: list  # [(empresa, tipo, "AAAA-MM-DD HH:MM" ou None)]

    @property
    def alerta(self) -> bool:
        return self.dias is None or self.dias > DIAS_ALERTA_SINCRONIZACAO

    @property
    def texto(self) -> str:
        if self.dias is None:
            return "nunca sincronizado"
        if self.dias == 0:
            return "sincronizado hoje"
        return f"sincronizado há {self.dias} dia{'s' if self.dias != 1 else ''}"

    @property
    def dica(self) -> str:
        """Texto do title: o último sucesso de cada empresa × tipo."""
        return " · ".join(
            f"{e} {'despesas' if t == 'contas' else 'receitas'}: {q or 'nunca'}"
            for e, t, q in self.detalhe
        )


def selo(escopo, hoje: date | None = None) -> SeloSincronizacao | None:
    """A idade do dado mais VELHO dentro do escopo: se uma empresa ou um tipo
    parou de sincronizar, o selo mostra isso, mesmo que as outras estejam em dia.

    Vem da tabela `sincronizacoes` (último sucesso); quem nunca teve execução
    registrada cai no `atualizado_em` mais recente das próprias linhas."""
    hoje = hoje or datetime.now(FUSO_BRASILIA).date()
    filtro, params = clausula(escopo)
    conn = get_conn()
    try:
        empresas = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT empresa FROM contas_pagar WHERE {filtro}"
                f" UNION SELECT DISTINCT empresa FROM notas WHERE {filtro}",
                params * 2,
            )
        ]
        if not empresas:
            return None
        sucesso = {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                "SELECT empresa, tipo, MAX(terminada_em) FROM sincronizacoes"
                " WHERE status = 'ok' GROUP BY empresa, tipo"
            )
        }
        detalhe = []
        for empresa in sorted(empresas):
            for tipo, tabela in (("contas", "contas_pagar"), ("notas", "notas")):
                quando = sucesso.get((empresa, tipo))
                if quando is None:
                    # Sem histórico (dado anterior à Fase 1): a gravação mais recente.
                    bruto = conn.execute(
                        f"SELECT MAX(atualizado_em) FROM {tabela} WHERE empresa = ?", (empresa,)
                    ).fetchone()[0]
                    if bruto:
                        quando = (
                            datetime.fromisoformat(bruto)
                            .astimezone(FUSO_BRASILIA)
                            .replace(tzinfo=None)
                            .isoformat(timespec="seconds")
                        )
                detalhe.append((empresa, tipo, quando[:16].replace("T", " ") if quando else None))
    finally:
        conn.close()

    datas = [q for _, _, q in detalhe]
    if any(q is None for q in datas):
        return SeloSincronizacao(None, detalhe)
    mais_velha = min(date.fromisoformat(q[:10]) for q in datas)
    return SeloSincronizacao((hoje - mais_velha).days, detalhe)
