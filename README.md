# Grupo Start — Fechamento

Espelho do Tiny ERP (Olist) para o fechamento gerencial de três empresas do
grupo: despesas (contas a pagar) e receitas (notas fiscais) sincronizadas pela
API oficial v2, com resultado por centro de custo, imposto e rateio do
administrativo.

O sistema **não corrige dado do ERP**: o que vem do Tiny é gravado como veio, e a
sujeira encontrada é reportada (`scripts/relatorio_qualidade.py`) para ser
corrigida na origem. Ajustes manuais ficam em colunas próprias, ao lado do
original, e cada um é registrado na trilha de auditoria.

## Stack

Python 3.11+ · Flask · Jinja2 · SQLite (`sqlite3`) · JavaScript puro, sem etapa
de build. Destino: PythonAnywhere.

## Estrutura

```
app.py                       ponto de entrada local (python app.py -> :5000)
app/__init__.py              criar_app(): config, banco, log, rotas, erros
app/configuracao.py          variáveis GSF_* lidas só do .env do projeto
app/web/                     rotas finas, um blueprint por área
app/paineis.py               o que cada tela mostra (regra fora das rotas)
app/db.py                    conexão, migrações versionadas, backup
app/migracoes/               000N_nome.sql — nunca editar migração aplicada
app/dinheiro.py              centavos no banco, Decimal no cálculo, rateio exato
app/centros_de_custo.py      resultado por categoria: imposto, Adm I, Adm II
app/auditoria.py             trilha append-only de toda escrita manual
app/sincronizar_tudo.py      job único de sincronização (tela, CLI, agendada)
app/registro.py              log com rotação e máscara de token/CPF/CNPJ
scripts/                     sincronizar, tarefa_diaria, relatorio_qualidade...
tests/                       pytest com dados sintéticos + golden master local
```

## Como rodar

```
python -m venv .venv
.venv\Scripts\pip install ".[dev]"
copy .env.example .env          (preencher GSF_SECRET_KEY e os tokens do Tiny)
.venv\Scripts\python scripts\diagnosticar_env.py
.venv\Scripts\python app.py
```

Na primeira subida, o sistema aplica as migrações pendentes com backup
verificado em `backups/`.

## Sincronização

```
.venv\Scripts\python scripts\sincronizar.py TODAS 2026          despesas e notas
.venv\Scripts\python scripts\sincronizar.py MSV 2026 --so notas
.venv\Scripts\python scripts\tarefa_diaria.py                   backup + sync + relatório
```

Cada execução fica registrada na tabela `sincronizacoes`.

## Testes

```
.venv\Scripts\python -m pytest            unitários (dados sintéticos) + golden
.venv\Scripts\ruff check .
.venv\Scripts\pre-commit install          uma vez por clone
```

O **golden master** (`tests/golden/`) congela os números de todas as telas
sobre uma cópia do banco e é o juiz de qualquer refatoração. Os valores
esperados são dados reais e ficam fora do git (`tests/golden/esperado/`):
no CI ele aparece como *pulado*, e roda localmente antes de cada merge.
Mudança de número só entra com `python -m tests.golden.comparar --aceitar
"motivo"`, que guarda a fotografia anterior e registra o motivo.

## Segurança do repositório

Repositório público. `.gitignore` e hook `pre-commit` (gitleaks, bloqueio de
`.db`, `.xls*`, `.env`, `.pkl` e de arquivo acima de 1 MB) impedem que banco,
planilha ou segredo entrem no histórico. Nenhum arquivo versionado pode conter
valor real, nome de cliente ou fornecedor, nem descrição de infraestrutura.
