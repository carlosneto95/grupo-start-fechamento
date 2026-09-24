# Grupo Start - Fechamento

Automação da extração de relatórios do Tiny ERP (Olist), consolidando os dados
de 3 empresas diferentes (mesmo sistema, contas separadas) em uma única
planilha, substituindo o processo manual em Excel.

## Status atual

Estrutura inicial do projeto. Ainda validando, para a EMPRESA 1, se dá para
usar a API oficial do Tiny ou se será necessário o fallback via requisição
HTTP direta (sessão logada).

## Estrutura

```
app/
  config/companies.py   -> carrega credenciais das 3 empresas via .env
  tiny_client/
    api_client.py        -> cliente da API oficial do Tiny
    http_client.py        -> fallback via sessão HTTP (login simulado)
  reports/consolidar.py  -> junta as planilhas das 3 empresas em uma só
scripts/testar_conexao.py -> testa a conexão com a EMPRESA 1
app.py                    -> dashboard Flask (base inicial)
templates/, static/       -> front-end HTML
```

## Como rodar localmente

```
pip install -r requirements.txt
cp .env.example .env   # preencher com os dados da EMPRESA1
python scripts/testar_conexao.py
```

## Deploy

Alvo final: PythonAnywhere (plano pago). A extração usa API oficial ou
requests HTTP puro — **sem** automação de navegador (Selenium/Playwright),
que não é suportado de forma confiável no PythonAnywhere.
