# HISTÓRICO — Grupo Start · Fechamento

Um registro por fase: o que foi feito, as decisões e as pendências.
Este arquivo vai para o GitHub: **nenhum valor em reais, nome de cliente ou de
fornecedor aqui**. Os números ficam em `relatorios/` e `tests/golden/esperado/`
(fora do git).

**Versão no ar:** nenhuma (sistema só local; deploy é a Fase 5).

---

## Fase 4.2 — Fechamento de competência · 24/09/2026 · validada pelo Neto e mesclada (PR #10)

### Decisões do Neto (antes de construir)
1. Mês fechado: o Dashboard mostra o **número vivo + alerta** quando o atual difere do
   fechado (não o número congelado).
2. Ajustes manuais do mês fechado (Considerar/Desconsiderar, competência e categoria de
   nota) ficam **travados** até um Admin reabrir.

### O que foi feito
- **Migração 5** (`fechamentos`, `fechamento_linhas`): fechar grava a foto de cada conta e
  nota da competência, de todas as empresas (valor, considerada, categoria). A foto é
  imutável (triggers); no fechamento, só a reabertura pode ser gravada, uma vez, com
  motivo. No máximo um fechamento vigente por competência; o histórico guarda todos.
- **Tela Fechamento** (menu; todos os perfis veem, só Admin fecha e reabre): um cartão por
  mês de 01/2026 até o corrente, com o estado e, se fechado, quantas linhas mudaram e o
  efeito em receita e despesa. Fechar pede confirmação no próprio formulário.
- **Tela de diferenças**: resultado no fechamento × agora (recalculado da foto pelo mesmo
  `separar()` do Dashboard, dentro do escopo de quem olha) e a tabela das linhas que
  mudaram — entrou no mês, saiu do mês (e para onde foi), alterada (valor, considerar,
  categoria) — com antes, agora e efeito; ordenável e filtrável pelo cabeçalho. A cor
  segue o efeito no resultado (custo que sobe é vermelho).
- **Dashboard**: faixa de alerta para cada mês fechado do recorte que difere do atual.
- **Trava** (`app/trava_fechamento.py`): marcar ou ajustar linha de mês fechado responde
  409 "competência fechada"; mover nota PARA um mês fechado também. A sincronização não é
  travada (espelho do Tiny): vira diferença. Mudança de regra de exclusão também aparece.
- **Auditoria**: fechar e reabrir (com o motivo).
- **Desempenho**: as três listas de opções do Dashboard viraram uma varredura só (mesmas
  listas, conferido). Dashboard: ~250 ms sem mês fechado (antes 330–430 ms) e ~300 ms com
  os oito meses de 2026 fechados e o alerta ativo.
- Testes: 287 (20 novos: foto, diferenças, alerta, trava, reabertura, escopo,
  imutabilidade). Golden idêntico.

### Decisões
1. Fechamento é do grupo (todas as empresas); a visão das diferenças respeita o escopo.
2. Pode-se fechar até o mês corrente; o Admin decide quando (o sistema não impede fechar
   com pendência — a tela Pendências mostra o que falta).
3. Menu: "Receitas Vendas" e "Receitas Serviços" viraram "Vendas" e "Serviços" para caber
   o item Fechamento em 1366 px (os títulos das telas continuam completos).

---

## Fase 4.1 — Painel de pendências de dados · 24/09/2026 · validada pelo Neto e mesclada (PR #9)

### O que foi feito
- **Tela Pendências** (menu, todos os perfis, dentro do escopo): o relatório de qualidade
  da Fase 0 ao vivo, em seis verificações — notas de serviço sem competência, notas
  consideradas como receita sem categoria, contas sem competência, contas sem
  categoria, competência fora do padrão (mês inválido, formato torto ou ano além de
  +10 anos) e fornecedores com grafia mudando só na caixa. Cada uma com contagem e
  valor por empresa, onde corrigir, e **link para as linhas** pelos filtros de coluna
  das telas (ex.: Despesas com Competência = "(vazio)"), montado com `url_for`.
- **Selo "sincronizado há N dias"** na barra de todas as telas: idade do dado mais
  velho dentro do escopo (último sucesso de cada empresa × tipo em `sincronizacoes`;
  sem histórico, a gravação mais recente das linhas). Verde até 2 dias, vermelho acima
  ou se algum par nunca sincronizou; o `title` mostra cada empresa. Leva à tela de
  Sincronizar (Admin) ou ao painel.
- Barra em 1366 px: com o item novo e o selo, o menu não cabia; até 1500 px o nome do
  usuário e o "Fechamento" ao lado do logo somem (a inicial fica, com o nome no `title`).
  Nenhum item de menu some; linhas visíveis mantidas (Despesas 20).
- **Achado**: o `{% set itens %}` do menu no `_base.html` sobrescrevia a variável de
  mesmo nome das telas; renomeado para `itens_menu`.
- Testes: 267 (12 novos, incluindo seguir o link de cada pendência e conferir que ele
  leva exatamente às linhas contadas). Golden idêntico.

### Retrato no banco real (24/09/2026, depois da sincronização)
Notas de serviço sem competência 42 · notas sem categoria consideradas 6 (as de
retorno/devolução que o Neto vai desconsiderar) · contas sem competência 132 · contas
sem categoria 59 · competência fora do padrão 2 · grupos de grafia divergente 50.
Selo: sincronizado hoje. Cálculo do painel: ~170 ms.

---

## Fase 3 — Identidade visual · 24/09/2026 · validada pelo Neto e mesclada (PR #8)

### O que foi feito
- **Família visual do Controle de Impostos**: paleta (fundo `#F4F1EA`, superfície
  `#FFFDF8`, barra `#1C1B19`, destaque `#0F5C55`, borda `#DDD7CA`, verde `#2E7D4F`,
  amarelo `#B7791F`, vermelho `#B42318`); receita em verde, despesa em vermelho, o índigo
  saiu. Os nomes dos tokens do CSS ficaram; mudaram os valores (a troca vale no sistema
  inteiro). As 12 cores fixas fora dos tokens foram migradas.
- **Fontes**: Fraunces nos títulos, IBM Plex Sans no texto, IBM Plex Mono com
  `tabular-nums` em todo número (valor, total, percentual, data, competência).
- **Barra superior escura** com o logo oficial do Grupo Start (o mesmo arquivo do
  Impostos), menu com ícone e texto (`templates/_icones.html`, SVG no HTML, sem CDN),
  usuário com a inicial e Sair à direita. Favicon do Impostos. Tela de login com o logo.
- **Selos, cartões, botões e links** no padrão do Impostos.
- **Densidade mantida** (conflito com o respiro do Impostos): a escala compacta das
  tabelas ficou; o total de Despesas e de Receitas subiu para a linha do título;
  limpar filtros e o aviso do limite dividem uma faixa só; texto longo numa linha com
  reticências (o completo no `title`) — linha que quebrava em duas dobrava de altura.
- **Gráficos**: o sistema não tem nenhum hoje; a regra (SVG gerado no servidor, sem
  biblioteca por CDN) vale para os que a Fase 4 criar.
- **`scripts/capturar_telas.py`**: sobe o sistema sobre o banco congelado, entra com
  usuário de teste e fotografa cada tela no Chrome sem interface, contando as linhas
  inteiramente visíveis. Mesma medida para antes e depois.

### Linhas visíveis sem rolar (1366×768; área útil de janela maximizada 1366×643)
| Tela | Antes | Depois |
|---|---:|---:|
| **Despesas** (critério de aceite) | 14 | **20** |
| Dashboard (quadro de resultado) | 10 | 10 |
| Receitas Vendas | 18 | 20 |
| Receitas Serviços | 18 | 20 |
| Análise de Receitas | 14 | 14 |

Capturas em `relatorios/capturas/antes` e `depois` (fora do git: mostram dados reais).
Testes: 255 (golden idêntico; o teste de segurança confere que nenhum template ganhou
script ou estilo inline).

### Decisões
1. Barra com 42 px de altura (56 px no Impostos): repete em toda tela e cada pixel é
   fração de linha de tabela.
2. Os cartões do Dashboard continuam numa faixa própria: três cartões com as notas de
   composição não cabem na linha do título em 1366 px sem espremer o texto; a tela
   manteve as 10 linhas de antes.
3. Tamanho da fonte das tabelas (11 px) mantido; números em 10,5 px na mono, que é
   mais larga.

---

## Fase 2 — Segurança da informação · 24/09/2026 · validada pelo Neto e mesclada (PR #7)

### O que foi feito
- **Login** (padrão do Impostos): hash scrypt, bloqueio de 15 min após 5 erros,
  mensagem única para login inexistente e senha errada (com tempo igualado), sessão
  de 60 min parada, cookie `gsf_sessao` HttpOnly/Secure/SameSite=Lax com caminho do
  prefixo, troca de senha obrigatória no primeiro acesso, sessões derrubadas ao mudar
  senha, perfil, empresas ou ativo. Proteção contra open redirect no `?proximo=`.
- **Perfis e escopo por empresa** (migração 4: `usuarios`, `usuario_empresa`):
  Admin, Financeiro e Leitura. `app/escopo.clausula()` entra em todo SQL de contas e
  notas e erra se o escopo faltar; perfil e empresas vêm do banco a cada requisição;
  escrita fora do escopo responde 404. Scripts e sincronização usam o escopo `SISTEMA`.
- **CSRF** (Flask-WTF 1.3.0, a versão do Impostos) em todo POST; `fetch` manda o token
  no cabeçalho (`static/js/csrf.js`); Sair é POST.
- **Headers**: CSP sem `unsafe-inline` (Google Fonts é a única origem externa), HSTS,
  X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, no-store.
  Os dois `style="..."` do Dashboard viraram classe.
- **Validação** (`app/validacao.py`) em toda rota de escrita; toda f-string com SQL
  revista (nome vem de constante ou lista branca; valor é sempre parâmetro).
- **LGPD**: listagem de notas deixou de ler o CPF/CNPJ do cliente;
  `mascarar_documento` pronto para quando alguma tela o mostrar.
- **Usuários**: tela Admin → Usuários (tabela ordenável e filtrável), criação com
  senha provisória mostrada uma vez, edição, redefinição de senha;
  `scripts/criar_usuario.py` pelo terminal. Admin não rebaixa nem desativa a si mesmo.
- **Auditoria**: autor passa a ser o usuário logado; login, falha, bloqueio, logout,
  acesso negado, criação e alteração de usuário registrados.
- **Achado no caminho**: salvar a tela de regras de exclusão apagava regra cujo valor
  não tinha conta na visão (latente: hoje as 5 regras têm conta), e o formulário
  aceitava categoria inventada. Corrigido e testado.
- **Revisão final**: `tests/test_seguranca.py` (adaptado do `revisao_seguranca.py` do
  Novos Convertidos) — 84 testes: sem login, outra empresa, perfil, CSRF, headers,
  login, sessão, troca de senha, usuários, escopo, SQL, LGPD, validação.
- **Testes: 255.** Golden master idêntico (o Admin vê os mesmos números de antes).
  `pip-audit`: nenhuma vulnerabilidade conhecida.
- Banco local migrado para a versão 4 (backup `backups/app_20260924_175531_antes_v4.db`);
  usuário `neto` (Admin) criado com senha provisória e troca obrigatória.
- Relatório de riscos antes e depois em `relatorios/` (fora do git: o repositório é
  público).

### Decisões
1. Usuários: só o Neto, como Admin (decisão do Neto). Os demais pela tela.
2. Financeiro não sincroniza nem mexe em regra de exclusão (valem para as três
   empresas e consomem a cota da API de todas).
3. Admin vê todas as empresas sem precisar de atribuição, inclusive uma nova.
4. Escrita fora do escopo = 404 (não confirma que o registro existe); tela de Admin
   negada = 403 (a tela existe, só não é para o perfil), com registro na auditoria.
5. `.env` local com `GSF_COOKIE_SEGURO=0` (HTTP em 127.0.0.1); produção fica com o
   padrão, ligado.
6. Exportação para Excel (item 7) não existe ainda: a neutralização de fórmula entra
   junto com ela, na Fase 4.

### Pendências
- ~~Neto: entrar com a senha provisória e definir a própria~~ — feito em 24/09/2026 18:17 (auditoria).
- Fase 5: `.env` com permissão 600, `GSF_PREFIXO`, Force HTTPS.

---

## Fase 1 — Estrutura técnica · 24/09/2026 · validada pelo Neto e mesclada (PR #6)

### O que foi feito
- **Estrutura**: fábrica `criar_app()` (padrão do Impostos); rotas finas em
  `app/web/` (dashboard, despesas, receitas, análise, extração, admin, api); a regra
  que morava em `app.py` foi para `app/paineis.py` sem mudar cálculo (golden idêntico).
  `app.py` virou só ponto de entrada; `debug` do Flask desligado.
- **Configuração** só do `.env` do projeto, prefixo `GSF_`, lida com `dotenv_values`;
  sem `GSF_SECRET_KEY` de 32+ caracteres o app não sobe. O `.env` local foi renomeado
  para os nomes novos (backup em `backups/`, nenhum valor exibido) e ganhou uma chave
  gerada. Os tokens do Tiny deixaram de ir para `os.environ`.
- **Migrações versionadas** (`app/migracoes/`, `db.MIGRACOES`), aplicadas no
  `criar_app` com backup verificado antes e uma transação por migração:
  1 = esquema de antes; 2 = integridade (CHECK nas colunas que o sistema escreve,
  índices dos filtros), `auditoria` e `sincronizacoes`; 3 = dinheiro em centavos.
- **Dinheiro em centavos** (`*_centavos INTEGER`), `Decimal` no cálculo, meio centavo
  sobe (`ROUND_HALF_UP`), rateio com resíduo na maior parte (`dinheiro.ratear`). Prova
  de reconciliação linha a linha e por empresa × competência × coluna; qualquer
  diferença desfaz a migração (testado).
- **journal_mode DELETE**, o mesmo do Impostos em produção (WAL não verificado no
  PythonAnywhere; na dúvida, o que já roda lá).
- **Auditoria** append-only (triggers) em toda escrita manual: marcar, ajustar nota,
  regras de exclusão e a importação de competências. Registro inexistente → 404;
  valor recusado pelo CHECK → 400.
- **Sincronização unificada** (`app/sincronizar_tudo.py`): contas e notas das três
  empresas no mesmo job, usado pela tela (agora com "Todas"), pela linha de comando e
  por `scripts/tarefa_diaria.py` (backup 30 dias + sync + relatório). Histórico em
  `sincronizacoes`; falha numa empresa não derruba as outras.
- **Erros e log**: tela genérica; `logs/app.log` com rotação (5 × 1 MB) e máscara de
  token, senha e CPF/CNPJ em mensagem e traceback.
- **Tela Sincronizar** sem `alert()`/`confirm()` e sem `innerHTML` com dado do Tiny
  (fechava um XSS por nome de fornecedor). JS sem caminho fixo (prefixo de produção).
- **Correções de bug** achadas no caminho: `importar_competencias_notas.py` atualizava
  nota sem filtrar a empresa; scripts ignoravam `GSF_BANCO`; abertura só-leitura
  quebrava com espaço no caminho (relatório e tarefa diária falhariam); relatório de
  qualidade somaria `float` com `Decimal`.
- **Banco local migrado** (versão 3), com backup `backups/app_20260924_002608_antes_v1.db`:
  reconciliação ok (28.528 contas, 1.135 notas), integridade ok, 15 MB após VACUUM.
  A fotografia do banco real bate com o golden: 0 diferenças.
- **Testes: 169** (unitários sintéticos + golden). `ruff check` limpo.

### Golden master — o que mudou de número, e por quê
Cada etapa está em `tests/golden/esperado/diff_*.md` (fora do git) e no histórico do
`meta.json`, com a fotografia anterior guardada.
1. **Centavos/Decimal** — 413 diferenças, só nos quadros do Dashboard, máximo de 4
   centavos: imposto arredondado por linha, resíduo do rateio na maior receita e o
   10% do ADM GERAL arredondado para Vendas com o complemento exato para Serviços.
   Receita, despesa, contagens e funis idênticos. 0 violações das regras verificadas.
2. **Conta sem competência aparece** (item 2) — entram exatamente as 134 contas do
   relatório da Fase 0, só nos recortes sem filtro de competência.
3. **Dashboard sem filtro = 01/2026 até o último mês com receita** (item 3) — só os
   cenários sem filtro mudam; cada um é a soma exata dos oito meses.
4. **Adm sem receita para absorver vira linha** (item 4, opção a) — 24 recortes (os do
   relatório da Fase 0); em todos os cenários o Total carrega o bolo inteiro de Adm.
5. **Ordem do funil determinística** (item 5) — mesmas listas, só a ordem.

### Desempenho (banco congelado, mediana, máquina local)
| Rota | Antes | Depois | Meta 300 ms |
|---|---:|---:|---|
| /despesas (15,6 mil linhas) | 1.743 ms | ~190 ms | atingida (2 mil linhas na tela) |
| /dashboard | 643 ms | ~280 ms | atingida |
| /api/valores-filtro (fornecedor) | 365 ms | ~115 ms | atingida |
| /api/valores-filtro (competência) | 357 ms | ~115 ms | atingida |

Em /despesas, montar os dados custa ~170 ms; renderizar 15,6 mil linhas levava ~300 ms.
Decisão do Neto: a tela desenha até 2 mil linhas, com "Mostrar todas"; total, contagem
e funis continuam sobre todas as linhas do recorte.

### Decisões
1. Pacote continua `app/` (renomear para `sistema/` mudaria todos os imports sem ganho).
2. Colunas monetárias renomeadas (`valor` → `valor_centavos`): quem lê o banco direto
   não confunde centavos com reais.
3. Regras de exclusão **não** cacheadas: já eram lidas uma vez por listagem (< 1 ms), e
   um cache arriscaria worker do PythonAnywhere somando com regra velha.
4. Uma trava por empresa cobre contas e notas (dividem a cota da API).
5. Não parei no meio da fase quando o golden mudou por centavos: a mudança decorre do
   item 4 da fase (Decimal + resíduo), está explicada linha a linha e fica numa branch
   sem merge até a validação.

### Código removido (com aval do Neto)
`app/tiny_client/http_client.py` (login simulado, nunca usado); `app/reports/consolidar.py`;
`combinar_registros`/`salvar` em `app/reports/contas_pagar.py` (únicos usos de pandas no
app); `arvore_datas`, `arvore_competencias`, `arvore_competencias_notas`,
`categorias_primarias_das_notas`, `resumir_por_categoria`, `resumir_receitas` e o
`sincronizacao.sincronizar` público (substituído pelo job único) — nenhuma referência.

### Validação do Neto (24/09/2026)
"De acordo com tudo": as cinco mudanças de número aprovadas (registrado no `meta.json`
do golden), Despesas limitada a 2 mil linhas na tela, código morto removido.
Também: fim de linha normalizado para LF (`.gitattributes`); o repositório nasceu
misturado e cada edição aparecia como troca do arquivo inteiro.

### Pendências
- Sincronizar as 3 empresas (paradas desde 25/08/2026) — agora pela tela, com "Todas".
- 4 PRs do Dependabot abertos (actions e pandas 3.0.6): o do pandas precisa do golden
  local antes do merge.

---

## Fase 0 — Fundação · 23/09/2026 · validada e mesclada (PR #1)

### O que foi feito
- **Backup** `backups/app_20260923_221922_antes_fase0.db` pela API de backup do SQLite,
  com `PRAGMA integrity_check = ok` na origem e na cópia, e contagem/soma idênticas
  nas três tabelas (28.528 contas, 1.135 notas, 5 regras).
- **Git local** na `main`, com `.gitignore` por seções (comentário sempre em linha
  própria), hook `pre-commit` (gitleaks, ruff, bloqueio de arquivo > 1 MB, chave
  privada e das extensões `.db`/`.xls*`/`.pkl`/`.csv`/`.env` — testado com `git add -f`),
  CI (`.github/workflows/ci.yml`: ruff, pytest sintético, pip-audit, gitleaks) e
  Dependabot semanal (pip e actions). Varredura antes do primeiro commit: gitleaks e
  detect-secrets sem achados.
- **Repositório no GitHub público** (decisão do Neto, 23/09/2026). Antes do primeiro push,
  o histórico local foi refeito para tirar o que não pode ser público: `CLAUDE.md` (dado
  pessoal do diretor), `PROMPT_MELHORIAS.md` (mapa da infraestrutura e das fragilidades
  abertas) e os valores de uma NFS-e real num comentário de `app/receitas.py` (trocados por
  valores ilustrativos com a mesma aritmética). Os dois `.md` continuam no disco, fora do git.
- **`pyproject.toml`** com as versões fixadas. O `requirements.txt` antigo estava
  desatualizado (Flask 3.0.3 e pandas 2.2.2 declarados; rodava Flask 3.1.3 e pandas 3.0.5,
  e o pandas 2.2.2 nem instala no Python atual). Agora os dois batem. `pip-audit`: nenhuma
  vulnerabilidade conhecida.
- **Testes unitários (dados sintéticos): 83**, cobrindo `valor_bruto_de_servico`,
  `casa_data`, `_considerar_efetivo` (despesas e receitas), `separar`, `valores`
  (cascata do funil, pela função e pela rota) e as telas (contexto capturado pelo sinal
  `template_rendered`, sem depender do HTML que a Fase 3 vai trocar).
- **Golden master** (`tests/golden/`): 227 cenários — telas com filtros padrão;
  Dashboard, Despesas, Receitas Vendas e Receitas Serviços para cada empresa (e o
  consolidado) × cada competência de 01/2026 a 08/2026 e sem slicer; análise de receitas;
  lista de todos os funis com e sem recorte. Roda sobre uma **cópia congelada** do banco
  (a sincronização muda o banco vivo, e o golden mediria dado em vez de código), com
  SHA-256 conferido. Tolerância: meio centavo. Estável em 3 execuções seguidas; teste de
  mutação (Vendas 14% → 15%) acusou 408 diferenças, cada uma com o caminho até a linha.
- **Relatório de qualidade de dados** (`scripts/relatorio_qualidade.py`, só leitura,
  `mode=ro`), gravado em `relatorios/qualidade_fase0.md`.
- `ruff check` limpo no projeto inteiro (regras de bug); `ruff format` só nos arquivos novos.

### Achados (detalhe com valores no relatório local)
1. **Sincronização parada há 29 dias** nas 3 empresas, despesas e notas (última gravação
   25/08/2026). Não existe registro de execução: a data sai do `atualizado_em`.
2. **134 contas sem competência somem da tela** (`substr(NULL)` no filtro). 51 delas têm
   vencimento em 2026 e 42 em 2027; a maior parte é GASTOS FIXO.
3. **O Dashboard sem slicer soma parcelas até 2032** (e uma competência 07/2800). Cerca de
   **50% da despesa considerada** do Total sem slicer é de competência posterior a 09/2026,
   contra uma receita que para em 08/2026. Esse Total não é resultado de período nenhum.
4. **Adm rateado some quando o bloco não tem receita no recorte.** Com o filtro de uma
   empresa, os 90% do ADM GERAL que cabem a Serviços somem na MSV (sem receita de serviço),
   e os 10% de Vendas somem na GTF e em vários meses da START. O Resultado dessas visões
   fica maior do que a despesa permite. No consolidado mensal de 01 a 08/2026 não acontece.
5. **45 contas sem categoria na visão**, quase todas da MSV. Nenhuma nota considerada sem
   categoria hoje (as 18 de venda sem categoria estão todas desconsideradas).
6. **45 fornecedores com grafia que muda só na caixa** (ex.: `Fulano` × `FULANO`): aparecem
   duas vezes no funil e somam separados na árvore do Dashboard.
7. **Bug de código: a ordem do funil não é determinística** para esses fornecedores
   (`valores()` parte de um `set` e ordena por `casefold`, que empata). O golden achou.
8. **Risco latente:** a lista de situações sem receita tem `EXCLUIDA` sem acento — uma nota
   "Excluída" entraria como receita. Hoje não existe nenhuma no banco.
9. A regra de exclusão compara texto exato (`IMPOSTO` ≠ `Imposto`). Hoje não há grafia
   divergente de categoria, então sem efeito.
10. Comentário em `app/receitas.py` trazia os valores de uma NFS-e real — trocado por
    valores ilustrativos antes do primeiro push (repositório público).

### Decisões
1. Golden roda pelas rotas (contexto do template), não pelas funções: pega também a lógica
   que mora na rota (competência do Dashboard, tipo de nota fixo das telas de receita).
2. "Última competência fechada" = última competência com nota (08/2026). Despesa tem
   parcela até 2032 e não serve de sinal.
3. Comportamentos suspeitos (itens 4, 7, 8) ficaram **congelados como estão**, com teste que
   os documenta: corrigir agora mudaria número sem decisão registrada.
4. Ruff só com regras de bug nesta fase; estilo entra com a reescrita da Fase 1.
5. `.venv` no próprio projeto (fora do git) com as versões fixadas.
6. **Repositório público** (Neto, 23/09/2026). Consequência registrada: a partir daqui
   nenhum arquivo versionado pode ter dado pessoal, valor real, nome de cliente ou
   fornecedor, nem descrição de infraestrutura ou de fragilidade de segurança em aberto.
   O relatório de riscos da Fase 2 fica fora do git.
7. **Correções de visão aprovadas** (Neto, 23/09/2026, "o restante segue"): itens 2 (conta
   sem competência aparece como "(vazio)" em vez de sumir), 3 (Dashboard sem slicer abre no
   período 01/2026 até o último mês com receita, escrito no cabeçalho), 5 (ordem do funil
   determinística) e, no item 4, a opção recomendada: a cota de Adm sem receita para
   absorver vira linha própria, visível, em vez de sumir. Entram na Fase 1, cada uma com a
   diferença do golden master explicada linha a linha antes de regerar.

### GitHub (23/09/2026)
- Repositório **público** https://github.com/carlosneto95/grupo-start-fechamento, criado
  com o `gh` (instalado via winget). Autor dos commits: e-mail privado do GitHub
  (`...@users.noreply.github.com`), para o e-mail pessoal não ficar público.
- Ligados: Secret scanning, Push protection e Dependabot alerts.
- `main` protegida: só por PR, com os checks `testes` e `segredos` verdes e a branch
  atualizada; vale também para o administrador; sem force-push e sem apagar a branch.
  O PR exige 0 aprovações: com um único desenvolvedor, exigir 1 travaria todo merge.
- CI do PR #1 verde: 83 testes passaram e o golden foi pulado com aviso (o CI não tem o
  banco); `pip-audit` sem vulnerabilidade conhecida; gitleaks sem vazamento.

### Pendências
- Rodar a sincronização das 3 empresas **depois** de validado o golden (o golden usa a
  cópia congelada, então sincronizar não o invalida).
