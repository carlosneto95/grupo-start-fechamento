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
financeiro/__init__.py              criar_app(): config, banco, log, rotas, erros
financeiro/configuracao.py          variáveis GSF_* lidas só do .env do projeto
financeiro/web/                     rotas finas, um blueprint por área
financeiro/paineis.py               o que cada tela mostra (regra fora das rotas)
financeiro/db.py                    conexão, migrações versionadas, backup
financeiro/migracoes/               000N_nome.sql — nunca editar migração aplicada
financeiro/dinheiro.py              centavos no banco, Decimal no cálculo, rateio exato
financeiro/centros_de_custo.py      resultado por categoria: imposto, Adm I, Adm II
financeiro/auditoria.py             trilha append-only de toda escrita manual
financeiro/sincronizar_tudo.py      job único de sincronização (tela, CLI, agendada)
financeiro/registro.py              log com rotação e máscara de token/CPF/CNPJ
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

## Acesso

Todo acesso exige login. Perfis: **Admin** (as três empresas, regras de
exclusão, sincronização e usuários), **Financeiro** (empresas atribuídas; marca
e ajusta) e **Leitura** (empresas atribuídas; só consulta). O primeiro Admin é
criado pelo terminal; os demais, na tela Usuários:

```
.venv\Scripts\python scripts\criar_usuario.py --login fulano --nome "Fulano" --perfil admin
.venv\Scripts\python scripts\criar_usuario.py --login fulano --redefinir-senha
```

A senha é digitada sem aparecer na tela. Usuário criado pela tela recebe senha
provisória e é obrigado a trocá-la no primeiro acesso.

## Backups

- Antes de toda migração e de toda gravação em massa: cópia verificada
  (`PRAGMA integrity_check`) em `backups/`, fora da pasta servida.
- `scripts/tarefa_diaria.py` faz um backup diário e apaga os diários com mais
  de 30 dias (os de migração ficam).
- Cópia fora do servidor: baixe o arquivo mais recente de `backups/` pela aba
  Files do PythonAnywhere (ou pela API de arquivos dele) e guarde num local
  com acesso restrito. O arquivo tem dados financeiros e pessoais: nunca em
  pasta compartilhada nem em anexo de e-mail.

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
