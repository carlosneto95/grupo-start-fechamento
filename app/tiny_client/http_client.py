"""
Fallback: sessão HTTP autenticada no Tiny ERP / Olist (sem API, sem navegador).

Descoberto inspecionando o site (com a extensão do Chrome, sem nunca ler a
senha real do usuário):

1. Login é via Keycloak/OIDC:
   GET https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth
       ?client_id=tiny-webapp&redirect_uri=https://erp.tiny.com.br/login
       &scope=openid&response_type=code
   -> retorna uma página de login HTML com um <form> cuja "action" contém
      parâmetros de sessão únicos (session_code, execution, tab_id...).
   -> POST usuário/senha nesse action -> Keycloak redireciona de volta para
      o redirect_uri com "?code=..." -> erp.tiny.com.br troca o code por uma
      sessão autenticada (cookies).

2. Exportação do relatório "Contas a Pagar" (replicando exatamente o filtro
   manual "Todas > Período por competência > mês"):
   GET https://erp.olist.com/exportacao_contas_pagar
       ?tipoPeriodo=todasVencimento&criterio=periodo&tipoFiltroData=C
       &dataInicial=01/MM/AAAA&dataFinal=<ultimo dia>/MM/AAAA
       &semCompetencia=false&pagina=1&idCategoria=&idPortadorPsq=
       &idMarcacaoPsq=0&tipoDup=0&idContatoPesquisa=0&campoPesquisa=
       &opcFiltroSituacaoTransacao=&idFormaEstatico=0&pesquisa=&valor=
   -> a página já vem com o(s) link(s) de "Download" prontos (o Tiny gera o
      arquivo no servidor ao carregar essa página).

3. O link de "Download" não tem uma URL fixa no HTML (é `href="#"` com
   `onclick="baixarArquivo(N)"`), a URL real é montada em JavaScript.
   Como isso não é sensível (não depende da senha, só da sessão já
   autenticada), o método `_descobrir_padrao_download` busca o arquivo
   .js correspondente e extrai o padrão via regex.

Ainda não testado ponta a ponta com credenciais reais — rode
`scripts/testar_conexao.py` (ou um script dedicado) localmente com o .env
preenchido para validar e ajustar o que for preciso.
"""
from __future__ import annotations

import re
from calendar import monthrange
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

AUTH_URL = (
    "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth"
    "?client_id=tiny-webapp&redirect_uri=https://erp.olist.com/login"
    "&scope=openid&response_type=code"
)
EXPORTACAO_URL = "https://erp.olist.com/exportacao_contas_pagar"
EXPORTACAO_JS_URL = "https://erp.olist.com/templates/form.exportacao.contas.pagar.js"


class TinyHTTPError(Exception):
    pass


class TinyHTTPClient:
    def __init__(self, user: str, password: str, empresa_nome: str = ""):
        self.user = user
        self.password = password
        self.empresa_nome = empresa_nome
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        self._logado = False

    def login(self) -> None:
        resp = self.session.get(AUTH_URL, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        # O Tiny usa um componente customizado <react-login-wc action="..."> em vez de
        # um <form> tradicional, mas a URL de autenticação do Keycloak (com
        # session_code/execution/tab_id) está exposta como atributo no HTML estático.
        elemento = (
            soup.find("form")
            or soup.find(attrs={"action": re.compile("login-actions/authenticate")})
        )
        if elemento is None or not elemento.get("action"):
            raise TinyHTTPError(
                f"[{self.empresa_nome}] Não encontrei a URL de autenticação do Keycloak. "
                "O layout da página de login pode ter mudado."
            )

        action_url = elemento["action"]

        login_resp = self.session.post(
            action_url,
            data={"username": self.user, "password": self.password},
            timeout=30,
            allow_redirects=True,
        )

        if login_resp.status_code == 403 or "cloudflare" in login_resp.text.lower()[:2000]:
            raise TinyHTTPError(
                f"[{self.empresa_nome}] A requisição parece ter sido bloqueada por proteção "
                "anti-bot (Cloudflare). Login via requisição HTTP direta pode não ser viável "
                "para essa conta — pode ser necessário reavaliar a abordagem."
            )

        login_resp.raise_for_status()

        if "erp.tiny.com.br" not in login_resp.url and "erp.olist.com" not in login_resp.url:
            raise TinyHTTPError(
                f"[{self.empresa_nome}] Login não completou o redirecionamento esperado "
                f"(terminou em {login_resp.url}). Usuário/senha errados ou layout mudou."
            )

        if "usuário ou senha" in login_resp.text.lower() or "credenciais" in login_resp.text.lower():
            raise TinyHTTPError(f"[{self.empresa_nome}] Usuário ou senha incorretos.")

        self._logado = True
        self._ultima_url_login = login_resp.url
        self._ultimo_status_login = login_resp.status_code

    def diagnosticar_cookies(self) -> list[dict]:
        """Lista os cookies de sessão obtidos, só domínio/nome/se-tem-valor — nunca o valor."""
        return [
            {"dominio": c.domain, "nome": c.name, "tem_valor": bool(c.value)}
            for c in self.session.cookies
        ]

    def diagnosticar_sessao(self) -> dict:
        """Verifica se a sessão autenticada realmente vale em erp.olist.com (não só em
        erp.tiny.com.br). Não expõe nada sensível — só status/URL/tamanho da resposta."""
        resp = self.session.get("https://erp.olist.com/contas_pagar", timeout=30, allow_redirects=True)
        parece_autenticado = "contas a pagar" in resp.text.lower() and "login" not in resp.url.lower()
        return {
            "status_code": resp.status_code,
            "url_final": resp.url,
            "tamanho_resposta": len(resp.text),
            "parece_autenticado": parece_autenticado,
            "trecho_resposta": resp.text[:1500],
        }

    def _descobrir_padrao_download(self) -> str:
        """Busca o JS da página de exportação e extrai o template da URL de download.

        Retorna uma string com um placeholder {n} no lugar do índice do arquivo,
        ex: "https://erp.olist.com/download_exportacao.php?indice={n}&..."
        """
        resp = self.session.get(EXPORTACAO_JS_URL, timeout=30)
        resp.raise_for_status()

        match = re.search(r"function\s+baixarArquivo\s*\([^)]*\)\s*\{(.*?)\}", resp.text, re.S)
        if not match:
            raise TinyHTTPError(
                "Não encontrei a função baixarArquivo no JS da exportação. "
                "Pode ter mudado de nome/arquivo — inspecionar novamente."
            )
        corpo = match.group(1)

        url_match = re.search(r"""['"](/[^'"]*exporta[^'"]*)['"]""", corpo, re.I)
        if not url_match:
            raise TinyHTTPError(
                f"Não consegui extrair o padrão de URL de download do JS. Trecho: {corpo[:300]}"
            )

        return url_match.group(1)

    def baixar_contas_pagar_mes(self, ano: int, mes: int) -> list[bytes]:
        """Baixa o(s) arquivo(s) .xls de Contas a Pagar filtrando por competência no mês/ano dado."""
        if not self._logado:
            self.login()

        ultimo_dia = monthrange(ano, mes)[1]
        params = {
            "tipoPeriodo": "todasVencimento",
            "pesquisa": "",
            "criterio": "periodo",
            "valor": "",
            "idCategoria": "",
            "tipoFiltroData": "C",  # C = competência
            "dataInicial": f"01/{mes:02d}/{ano}",
            "dataFinal": f"{ultimo_dia:02d}/{mes:02d}/{ano}",
            "idPortadorPsq": "",
            "pagina": "1",
            "idMarcacaoPsq": "0",
            "tipoDup": "0",
            "idContatoPesquisa": "0",
            "campoPesquisa": "",
            "opcFiltroSituacaoTransacao": "",
            "idFormaEstatico": "0",
            "semCompetencia": "false",
        }

        resp = self.session.get(EXPORTACAO_URL, params=params, timeout=60)
        resp.raise_for_status()

        indices = sorted(set(int(i) for i in re.findall(r"baixarArquivo\((\d+)\)", resp.text)))
        if not indices:
            raise TinyHTTPError(
                f"[{self.empresa_nome}] Nenhum arquivo de exportação encontrado para "
                f"{mes:02d}/{ano} — pode não haver contas nesse período, ou o layout mudou."
            )

        padrao_url = self._descobrir_padrao_download()

        arquivos = []
        for indice in indices:
            url = urljoin("https://erp.olist.com", padrao_url.replace("{n}", str(indice)))
            if "{n}" not in padrao_url:
                # o índice provavelmente vai como querystring; tentamos algumas variações comuns
                url = urljoin("https://erp.olist.com", padrao_url)
                dl_resp = self.session.get(url, params={"indice": indice}, timeout=60)
            else:
                dl_resp = self.session.get(url, timeout=60)
            dl_resp.raise_for_status()
            arquivos.append(dl_resp.content)

        return arquivos
