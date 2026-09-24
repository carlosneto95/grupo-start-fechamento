"""
Cliente para a API oficial do Tiny ERP (Olist) — v2, autenticação por token.

Documentação:
  - Info da conta:            https://tiny.com.br/api-docs/api2-info
  - Pesquisar Contas a Pagar:  https://tiny.com.br/api-docs/api2-contas-pagar-pesquisar
  - Obter Conta a Pagar:       https://tiny.com.br/api-docs/api2-contas-pagar-obter

Limitação conhecida: a busca (pesquisa.php) não filtra por competência — ela só
aparece no detalhe (conta.pagar.obter.php), uma conta por chamada. Por isso a
sincronização lista primeiro (barato, 100 por chamada) e só busca o detalhe de
quem é novo ou mudou. Ver app/sincronizacao.py.

A API v3 foi avaliada e descartada: mesmo limite de requisições, a listagem dela
também não traz competência, e exigiria migrar para OAuth2. O ganho seria só de
qualidade de dados (formaPagamento e valorPago como campos próprios, em vez de
extraídos do histórico por regex).
"""
from __future__ import annotations

import time
from datetime import date

import requests

BASE_URL = "https://api.tiny.com.br/api2"

# A API informa o limite da conta no cabeçalho "x-limit-api" (chamadas por minuto).
# Trabalhamos a uma fração dele: usar a capacidade cheia faz estourar por qualquer
# variação de rede, e cada estouro custa 60s parado — sai muito mais caro do que
# andar um pouco mais devagar.
FRACAO_DO_LIMITE = 0.80
INTERVALO_PADRAO = 1.25  # usado até a API nos dizer o limite real
ESPERA_APOS_BLOQUEIO = 60  # segundos
MAX_TENTATIVAS_BLOQUEIO = 3

# Uma queda momentânea de internet não pode matar um trabalho de 30 minutos:
# insistimos por vários minutos antes de desistir.
MAX_TENTATIVAS_REDE = 6
ESPERAS_REDE = [10, 30, 60, 120, 180, 300]  # segundos entre as tentativas


class TinyAPIError(Exception):
    pass


class TinyAPIClient:
    def __init__(self, token: str, empresa_nome: str = ""):
        self.token = token
        self.empresa_nome = empresa_nome
        self._ultima_chamada = 0.0
        self._intervalo_base = INTERVALO_PADRAO
        # Cresce a cada bloqueio e nunca diminui dentro da mesma execução: sem isso,
        # a próxima resposta bem-sucedida recalcularia o intervalo pelo cabeçalho e
        # apagaria o afrouxamento, fazendo a gente estourar de novo em seguida.
        self._fator_folga = 1.0

    @property
    def _intervalo(self) -> float:
        return self._intervalo_base * self._fator_folga

    def _afrouxar_ritmo(self) -> None:
        self._fator_folga = min(self._fator_folga * 1.25, 4.0)

    def _ajustar_ritmo(self, resp) -> None:
        """A resposta traz o limite da conta (chamadas/min) — usa isso para acertar
        o intervalo, em vez de depender de um valor chutado."""
        limite = resp.headers.get("x-limit-api")
        if not limite:
            return
        try:
            por_minuto = float(limite)
        except ValueError:
            return
        if por_minuto > 0:
            self._intervalo_base = max(60.0 / (por_minuto * FRACAO_DO_LIMITE), 0.5)

    def _post_com_retentativa_de_rede(self, endpoint: str, dados: dict):
        """Faz a chamada insistindo enquanto o problema for passageiro: internet
        caiu, DNS falhou, a requisição demorou, ou o servidor do Tiny respondeu
        erro 5xx (502/503/504 acontecem de vez em quando e passam sozinhos).

        Erro 4xx (token inválido, parâmetro errado) não é retentado — insistir não
        resolveria e só esconderia o problema real."""
        ultima_falha = None
        for tentativa in range(MAX_TENTATIVAS_REDE):
            motivo = None
            try:
                # Marca ANTES de disparar: o limite da API conta requisições por
                # minuto, então o intervalo tem que ser de início a início. Marcando
                # depois, o tempo da própria requisição somava ao intervalo e a gente
                # andava bem mais devagar do que o permitido.
                self._ultima_chamada = time.monotonic()
                resp = requests.post(f"{BASE_URL}/{endpoint}", data=dados, timeout=30)
                self._ajustar_ritmo(resp)

                if resp.status_code >= 500 or resp.status_code == 429:
                    ultima_falha = f"HTTP {resp.status_code}"
                    motivo = f"servidor do Tiny respondeu {resp.status_code}"
                else:
                    resp.raise_for_status()
                    return resp
            except (requests.ConnectionError, requests.Timeout) as e:
                ultima_falha = e
                motivo = "sem conexão com a API"

            if tentativa < MAX_TENTATIVAS_REDE - 1:
                espera = ESPERAS_REDE[tentativa]
                print(f"  ({motivo}; tentando de novo em {espera}s...)")
                time.sleep(espera)

        raise TinyAPIError(
            f"[{self.empresa_nome}] A API do Tiny não respondeu após "
            f"{MAX_TENTATIVAS_REDE} tentativas. Detalhe: {ultima_falha}"
        )

    def _post(self, endpoint: str, dados: dict | None = None) -> dict:
        dados = dados or {}
        dados.update({"token": self.token, "formato": "json"})

        for tentativa in range(1, MAX_TENTATIVAS_BLOQUEIO + 1):
            espera = self._intervalo - (time.monotonic() - self._ultima_chamada)
            if espera > 0:
                time.sleep(espera)

            resp = self._post_com_retentativa_de_rede(endpoint, dados)
            data = resp.json()

            status = data.get("retorno", {}).get("status")
            if status == "Erro":
                erros = data.get("retorno", {}).get("erros", [])
                mensagens = " ".join(str(e) for e in erros).lower()

                # "Não retornou registros" não é falha: é busca sem resultado.
                # A API do Tiny devolve isso como erro, mas para nós é lista vazia.
                if "não retornou registros" in mensagens or "nao retornou registros" in mensagens:
                    return {"retorno": {"status": "OK", "contas": [], "numero_paginas": 1}}

                bloqueado = "bloqueada" in mensagens or "excedido" in mensagens
                if bloqueado and tentativa < MAX_TENTATIVAS_BLOQUEIO:
                    # Levou bloqueio mesmo no ritmo calculado: afrouxa mais um pouco,
                    # senão a gente volta a estourar logo em seguida.
                    self._afrouxar_ritmo()
                    print(
                        f"  (rate limit da API; esperando {ESPERA_APOS_BLOQUEIO}s e "
                        f"reduzindo o ritmo para {self._intervalo:.2f}s entre chamadas)"
                    )
                    time.sleep(ESPERA_APOS_BLOQUEIO)
                    continue
                raise TinyAPIError(f"[{self.empresa_nome}] Erro na API Tiny em {endpoint}: {erros}")

            return data

    def testar_conexao(self) -> bool:
        """Chama um endpoint leve só para confirmar que o token é válido."""
        try:
            self._post("info.php")
            return True
        except Exception:
            return False

    def _pesquisar_contas_pagar_pagina(self, params: dict, pagina: int) -> tuple[list[dict], int]:
        dados = dict(params)
        dados["pagina"] = pagina
        resp = self._post("contas.pagar.pesquisa.php", dados)
        retorno = resp.get("retorno", {})

        brutos = retorno.get("contas", []) or []
        # A API do Tiny costuma envelopar cada item num dicionário {"conta": {...}} —
        # mas tratamos os dois formatos por segurança, caso isso não se confirme.
        registros = [item.get("conta", item) if isinstance(item, dict) else item for item in brutos]

        numero_paginas = int(retorno.get("numero_paginas", 1) or 1)
        return registros, numero_paginas

    def _pesquisar_contas_pagar(self, params: dict) -> list[dict]:
        todos = []
        pagina = 1
        while True:
            registros, numero_paginas = self._pesquisar_contas_pagar_pagina(params, pagina)
            todos.extend(registros)
            if pagina >= numero_paginas:
                break
            pagina += 1
        return todos

    def obter_conta_pagar(self, id_conta) -> dict:
        resp = self._post("conta.pagar.obter.php", {"id": id_conta})
        return resp.get("retorno", {}).get("conta", {})

    def listar_resumo(
        self,
        data_ini: date,
        data_fim: date,
        progresso=None,
        por: tuple[str, ...] = ("emissao", "vencimento"),
    ) -> dict[str, dict]:
        """Varre o período pela LISTAGEM (barata: até 100 contas por chamada).

        `por` escolhe quais datas filtrar: ("emissao",), ("vencimento",) ou as duas
        (padrão, unindo os resultados). Usar só uma reduz bastante o volume.

        Devolve {id: resumo}. O resumo não tem competência nem categoria — para
        isso é preciso `obter_conta_pagar` — mas já traz valor, saldo, situação e
        datas, o que basta para detectar o que mudou sem pagar o preço do detalhe.
        """
        d_ini = data_ini.strftime("%d/%m/%Y")
        d_fim = data_fim.strftime("%d/%m/%Y")

        campos = {
            "emissao": ("data_ini_emissao", "data_fim_emissao"),
            "vencimento": ("data_ini_vencimento", "data_fim_vencimento"),
        }
        desconhecidos = set(por) - set(campos)
        if desconhecidos:
            raise ValueError(f"filtro de data inválido: {desconhecidos}")

        resumos: dict[str, dict] = {}
        for campo_ini, campo_fim in (campos[p] for p in por):
            for r in self._pesquisar_contas_pagar({campo_ini: d_ini, campo_fim: d_fim}):
                if "id" in r:
                    resumos[str(r["id"])] = r
            if progresso:
                progresso(len(resumos))

        return resumos

    # ------------------------------------------------------------------
    # Receitas: notas fiscais emitidas
    #
    # Diferente de contas a pagar, aqui a listagem já traz valor, data, cliente
    # e situação — o detalhe só é preciso para categoria (serviço) e marcadores
    # (venda). E o volume é pequeno, então dá para detalhar tudo.
    # ------------------------------------------------------------------

    def _paginar(self, endpoint: str, params: dict, chave: str) -> list[dict]:
        itens: list[dict] = []
        pagina = 1
        while True:
            p = dict(params)
            p["pagina"] = pagina
            resp = self._post(endpoint, p)
            retorno = resp.get("retorno", {})
            pagina_itens = retorno.get(chave) or []
            itens.extend(pagina_itens)
            total_paginas = int(retorno.get("numero_paginas") or 1)
            if pagina >= total_paginas or not pagina_itens:
                break
            pagina += 1
        return itens

    def listar_notas_venda(self, data_ini: date, data_fim: date) -> list[dict]:
        """NF-e emitidas (tipoNota=S, ou seja saída — o que a empresa vendeu)."""
        brutos = self._paginar(
            "notas.fiscais.pesquisa.php",
            {
                "dataInicial": data_ini.strftime("%d/%m/%Y"),
                "dataFinal": data_fim.strftime("%d/%m/%Y"),
                "tipoNota": "S",
            },
            "notas_fiscais",
        )
        return [b.get("nota_fiscal", b) for b in brutos]

    def listar_notas_servico(self, data_ini: date, data_fim: date) -> list[dict]:
        """NFS-e emitidas."""
        brutos = self._paginar(
            "notas.servico.pesquisa.php",
            {
                "dataInicial": data_ini.strftime("%d/%m/%Y"),
                "dataFinal": data_fim.strftime("%d/%m/%Y"),
            },
            "notas_servico",
        )
        return [b.get("nota_servico", b) for b in brutos]

    def obter_nota_venda(self, id_nota) -> dict:
        resp = self._post("nota.fiscal.obter.php", {"id": id_nota})
        return resp.get("retorno", {}).get("nota_fiscal", {})

    def obter_nota_servico(self, id_nota) -> dict:
        # Apesar do nome do endpoint, o retorno vem sob a chave "nota_fiscal".
        resp = self._post("nota.servico.obter.php", {"id": id_nota})
        return resp.get("retorno", {}).get("nota_fiscal", {})
