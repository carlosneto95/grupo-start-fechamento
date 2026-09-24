// Filtro de coluna no estilo do AutoFiltro do Excel.
//
// Cada cabeçalho filtrável tem um funil. Ao abrir:
//   - a lista de valores é buscada no servidor (não vem com a página, porque
//     colunas como "fornecedor" têm mais de mil valores distintos);
//   - colunas de data e competência vêm em árvore Ano > Mês > Dia, cada nível
//     recolhível pelo botão +/−, como no Excel;
//   - há campo de busca, "selecionar tudo" e seleção múltipla;
//   - "Aplicar" reenvia o formulário com os valores marcados.
//
// A seleção vigente fica em inputs escondidos dentro do próprio formulário,
// então filtro e ordenação convivem sem se atropelar.
//
// Duas semânticas convivem de propósito:
//   - árvore de datas: nada marcado no servidor = tudo marcado na tela, e
//     marcar tudo limpa o filtro (é o comportamento do Excel). Dá para fazer
//     isso porque a árvore é completa e a seleção viaja colapsada (o ano vira
//     um parâmetro só).
//   - lista simples: começa desmarcada e o usuário escolhe o que quer. Aqui a
//     lista pode vir cortada em 400 itens, então "tudo marcado" seria mentira;
//     e desmarcar um item de 400 mandaria 399 valores na URL.

document.addEventListener("DOMContentLoaded", inicializarFiltrosDeColuna);

function inicializarFiltrosDeColuna() {
    document.querySelectorAll(".filtro-coluna").forEach(preparar);

    // Um clique fora fecha qualquer painel aberto.
    document.addEventListener("click", (e) => {
        if (!e.target.closest(".filtro-coluna")) fecharTodos();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") fecharTodos();
    });
}

function fecharTodos() {
    document.querySelectorAll(".filtro-coluna-painel").forEach((p) => {
        if (!p.hidden && p._soltar) p._soltar();  // para de acompanhar a rolagem
        p.hidden = true;
    });
}

const MARGEM = 8;        // respiro minimo ate a borda da janela
const ALTURA_MINIMA = 150; // abaixo disso nao vale a pena abrir para baixo

/** Coloca o painel logo abaixo do funil, sem sair da janela.
 *
 * O painel e `position: fixed` porque a caixa da tabela tem overflow e encolhe
 * conforme o filtro reduz as linhas — sendo absoluto, ela o recortava. Como
 * fixo nao acompanha ancestral nenhum, a posicao e recalculada aqui a cada
 * abertura e a cada rolagem enquanto ele estiver aberto. */
function posicionar(painel, botao) {
    const alvo = botao.getBoundingClientRect();
    const lista = painel.querySelector(".filtro-coluna-lista");

    // Mede o painel sem o limite anterior, para saber a altura que ele quer.
    lista.style.maxHeight = "";
    const desejada = painel.offsetHeight;
    const largura = painel.offsetWidth;

    const abaixo = window.innerHeight - alvo.bottom - MARGEM * 2;
    const acima = alvo.top - MARGEM * 2;
    // Abre para cima quando embaixo nao cabe e em cima cabe melhor.
    const paraCima = desejada > abaixo && acima > abaixo && abaixo < ALTURA_MINIMA;
    const espaco = paraCima ? acima : abaixo;

    if (desejada > espaco) {
        // Encolhe a lista, nao o painel: busca e botoes continuam visiveis.
        const fixo = desejada - lista.offsetHeight;
        lista.style.maxHeight = Math.max(60, espaco - fixo) + "px";
    }

    const altura = painel.offsetHeight;
    painel.style.top = (paraCima ? alvo.top - altura - 4 : alvo.bottom + 4) + "px";
    // Alinhado a direita do funil, mas sem passar das bordas da janela.
    const direita = alvo.right - largura;
    painel.style.left = Math.max(
        MARGEM, Math.min(direita, window.innerWidth - largura - MARGEM)) + "px";
}

function preparar(container) {
    const botao = container.querySelector(".filtro-coluna-botao");
    const painel = container.querySelector(".filtro-coluna-painel");

    botao.addEventListener("click", async (e) => {
        e.stopPropagation();
        e.preventDefault();
        const estavaAberto = !painel.hidden;
        fecharTodos();
        if (estavaAberto) return;

        painel.hidden = false;
        posicionar(painel, botao);
        // Rolar a pagina ou a caixa da tabela move o funil; o painel acompanha.
        // `capture` para pegar tambem a rolagem dos containers internos.
        const acompanhar = () => posicionar(painel, botao);
        window.addEventListener("scroll", acompanhar, true);
        window.addEventListener("resize", acompanhar);
        painel._soltar = () => {
            window.removeEventListener("scroll", acompanhar, true);
            window.removeEventListener("resize", acompanhar);
        };
        // Carrega uma vez por abertura de página; reabrir usa o que já veio.
        if (!painel.dataset.carregado) await carregarValores(container, "");
        const busca = painel.querySelector(".filtro-coluna-busca");
        busca.focus();
        busca.select();
    });

    painel.addEventListener("click", (e) => e.stopPropagation());

    // Busca com atraso: evita disparar uma requisição por tecla digitada.
    let timer;
    const busca = painel.querySelector(".filtro-coluna-busca");
    busca.addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => carregarValores(container, e.target.value.trim()), 220);
    });
    // Enter aplica direto, sem obrigar a ir até o botão.
    busca.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        clearTimeout(timer);
        aplicar(container);
    });

    painel.querySelector(".filtro-coluna-todos").addEventListener("change", (e) => {
        painel.querySelectorAll(".filtro-coluna-valor").forEach((c) => {
            c.checked = e.target.checked;
            c.indeterminate = false;
        });
    });

    const lista = painel.querySelector(".filtro-coluna-lista");

    // Marcar item a item repercute no "(Selecionar tudo)", como no Excel.
    lista.addEventListener("change", (e) => {
        if (e.target.classList.contains("filtro-coluna-valor") && ehArvore(painel)) {
            propagarParaBaixo(e.target);
            recalcularAscendentes(e.target);
        }
        sincronizarTodos(painel);
    });

    // Botões +/− da árvore. Delegado, porque a árvore é remontada a cada busca.
    lista.addEventListener("click", (e) => {
        const botaoExpandir = e.target.closest(".expandir");
        if (!botaoExpandir) return;
        e.preventDefault();
        alternarRamo(botaoExpandir);
    });

    painel.querySelector(".filtro-coluna-aplicar").addEventListener("click", () => aplicar(container));
    painel.querySelector(".filtro-coluna-limpar").addEventListener("click", () => limpar(container));
}

function ehArvore(painel) {
    return painel.dataset.tipo === "arvore";
}

async function carregarValores(container, busca) {
    const painel = container.querySelector(".filtro-coluna-painel");
    const lista = painel.querySelector(".filtro-coluna-lista");
    const coluna = container.dataset.coluna;
    const tabela = container.dataset.tabela;

    lista.innerHTML = '<div class="filtro-coluna-aviso">carregando…</div>';

    let dados;
    try {
        // Manda os filtros vigentes junto: a lista vem em cascata, mostrando só
        // o que existe no recorte atual. Vai a query string da própria página,
        // que é o estado já aplicado — o servidor retira dela o filtro desta
        // coluna e ignora o que não for filtro (ordenar/direcao).
        const url = `/api/valores-filtro?tabela=${encodeURIComponent(tabela)}`
                  + `&coluna=${encodeURIComponent(coluna)}&q=${encodeURIComponent(busca)}`
                  + (location.search ? "&" + location.search.slice(1) : "");
        const resp = await fetch(url);
        dados = await resp.json();
        if (!resp.ok) throw new Error(dados.erro || "falha");
    } catch (e) {
        lista.innerHTML = `<div class="filtro-coluna-aviso erro">não consegui carregar: ${e.message}</div>`;
        return;
    }

    painel.dataset.tipo = dados.tipo;
    // Mantém marcado o que já está filtrando, mesmo fora da busca atual.
    const selecionados = new Set(selecaoAtual(container));

    if (dados.tipo === "arvore") {
        montarArvore(lista, dados.arvore, selecionados, Boolean(busca));
    } else {
        montarLista(lista, dados, selecionados);
    }

    painel.dataset.carregado = "1";
    sincronizarTodos(painel);
    // A lista mudou de tamanho: recoloca o painel para ele nao vazar da janela.
    posicionar(painel, container.querySelector(".filtro-coluna-botao"));
}

function montarLista(lista, dados, selecionados) {
    if (!dados.valores.length) {
        lista.innerHTML = '<div class="filtro-coluna-aviso">nenhum valor encontrado</div>';
    } else {
        lista.innerHTML = dados.valores.map((v) => {
            const marcado = selecionados.has(v) ? " checked" : "";
            return `<label class="filtro-coluna-item">
                        <input type="checkbox" class="filtro-coluna-valor"
                               value="${escapar(v)}"${marcado}>
                        <span title="${escapar(v)}">${escapar(v)}</span>
                    </label>`;
        }).join("");
    }

    if (dados.truncado) {
        lista.insertAdjacentHTML("beforeend",
            `<div class="filtro-coluna-aviso">mostrando ${dados.valores.length} de ${dados.total}
             — use a busca para refinar</div>`);
    }
}

// ---------------------------------------------------------------- árvore ---

function montarArvore(lista, nos, selecionados, buscando) {
    if (!nos.length) {
        lista.innerHTML = '<div class="filtro-coluna-aviso">nenhuma data encontrada</div>';
        return;
    }
    lista.innerHTML = `<ul class="arvore-filtro">${nos.map(desenharNo).join("")}</ul>`;

    // Sem filtro no servidor, o Excel mostra tudo marcado.
    const tudo = selecionados.size === 0;
    lista.querySelectorAll(":scope > ul > li").forEach((li) => marcarNo(li, selecionados, tudo));

    // Durante uma busca a árvore já vem enxuta: abrir tudo poupa cliques.
    if (buscando) lista.querySelectorAll(".expandir").forEach(alternarRamo);
}

function desenharNo(no) {
    const temFilhos = Boolean(no.filhos && no.filhos.length);
    const expandir = temFilhos
        ? '<button type="button" class="expandir" aria-expanded="false">+</button>'
        : '<span class="espaco-expandir"></span>';
    const sub = temFilhos
        ? `<ul class="ramo" hidden>${no.filhos.map(desenharNo).join("")}</ul>`
        : "";
    return `<li class="no-arvore">
                <div class="linha-arvore">
                    ${expandir}
                    <label class="filtro-coluna-item">
                        <input type="checkbox" class="filtro-coluna-valor" value="${escapar(no.valor)}">
                        <span title="${escapar(no.valor)}">${escapar(no.rotulo)}</span>
                    </label>
                </div>
                ${sub}
            </li>`;
}

function caixaDo(li) {
    return li.querySelector(":scope > .linha-arvore .filtro-coluna-valor");
}

function ramoDe(li) {
    return li.querySelector(":scope > ul.ramo");
}

/** Marca o nó conforme a seleção vigente; um pai marcado arrasta os filhos. */
function marcarNo(li, selecionados, herdado) {
    const caixa = caixaDo(li);
    const marcado = herdado || selecionados.has(caixa.value);
    const ramo = ramoDe(li);

    if (!ramo) {
        caixa.checked = marcado;
        caixa.indeterminate = false;
        return;
    }
    ramo.querySelectorAll(":scope > li").forEach((f) => marcarNo(f, selecionados, marcado));
    recalcularNo(li);
}

/** Estado do pai a partir dos filhos: cheio, vazio ou parcial. */
function recalcularNo(li) {
    const ramo = ramoDe(li);
    const caixa = caixaDo(li);
    if (!ramo) return;
    const filhos = [...ramo.querySelectorAll(":scope > li")].map(caixaDo);
    const cheios = filhos.filter((c) => c.checked && !c.indeterminate).length;
    const algum = filhos.some((c) => c.checked || c.indeterminate);
    caixa.checked = algum;
    caixa.indeterminate = algum && cheios !== filhos.length;
}

function propagarParaBaixo(caixa) {
    const li = caixa.closest("li.no-arvore");
    const ramo = li && ramoDe(li);
    if (!ramo) return;
    ramo.querySelectorAll(".filtro-coluna-valor").forEach((c) => {
        c.checked = caixa.checked;
        c.indeterminate = false;
    });
}

function recalcularAscendentes(caixa) {
    const proprio = caixa.closest("li.no-arvore");
    let li = proprio && proprio.parentElement.closest("li.no-arvore");
    while (li) {
        recalcularNo(li);
        li = li.parentElement.closest("li.no-arvore");
    }
}

function alternarRamo(botao) {
    const ramo = ramoDe(botao.closest("li.no-arvore"));
    if (!ramo) return;
    const abrindo = ramo.hidden;
    ramo.hidden = !abrindo;
    botao.textContent = abrindo ? "−" : "+";
    botao.setAttribute("aria-expanded", String(abrindo));
}

/** Valores marcados, colapsando o ramo cheio no nó de cima (ano em vez de 365 dias). */
function coletarArvore(ul) {
    const saida = [];
    ul.querySelectorAll(":scope > li.no-arvore").forEach((li) => {
        const caixa = caixaDo(li);
        const ramo = ramoDe(li);
        if (caixa.checked && !caixa.indeterminate) saida.push(caixa.value);
        else if (caixa.indeterminate && ramo) saida.push(...coletarArvore(ramo));
    });
    return saida;
}

// ------------------------------------------------------------- aplicação ---

/** Estado do "(Selecionar tudo)": marcado, vazio ou indeterminado. */
function sincronizarTodos(painel) {
    const raiz = ehArvore(painel)
        ? [...painel.querySelectorAll(".filtro-coluna-lista > ul > li")].map(caixaDo)
        : [...painel.querySelectorAll(".filtro-coluna-valor")];
    const cheios = raiz.filter((c) => c.checked && !c.indeterminate).length;
    const algum = raiz.some((c) => c.checked || c.indeterminate);
    const todos = painel.querySelector(".filtro-coluna-todos");
    todos.checked = algum;
    todos.indeterminate = algum && cheios !== raiz.length;
}

/** Valores atualmente aplicados nesta coluna (nos inputs escondidos). */
function selecaoAtual(container) {
    return [...container.querySelectorAll(".filtro-coluna-atual")].map((i) => i.value);
}

function aplicar(container) {
    const painel = container.querySelector(".filtro-coluna-painel");
    const busca = painel.querySelector(".filtro-coluna-busca").value.trim();
    const lista = painel.querySelector(".filtro-coluna-lista");

    let marcados;
    if (ehArvore(painel)) {
        const raizes = [...lista.querySelectorAll(":scope > ul > li")].map(caixaDo);
        const tudoMarcado = raizes.length > 0
            && raizes.every((c) => c.checked && !c.indeterminate);
        // Tudo marcado e sem busca = sem filtro, como no Excel. Com busca ativa
        // "tudo" é só o que a busca trouxe, então não dá para concluir isso.
        if (tudoMarcado && !busca) {
            escreverSelecao(container, []);
            container.closest("form").submit();
            return;
        }
        const raiz = lista.querySelector(":scope > ul");
        marcados = raiz ? coletarArvore(raiz) : [];
    } else {
        marcados = [...lista.querySelectorAll(".filtro-coluna-valor:checked")].map((c) => c.value);
    }

    // Se a busca estava ativa, os valores fora dela não estão na tela — preserva
    // os que já filtravam para não perder seleção sem o usuário perceber.
    const naTela = new Set([...lista.querySelectorAll(".filtro-coluna-valor")].map((c) => c.value));
    const preservados = busca ? selecaoAtual(container).filter((v) => !naTela.has(v)) : [];

    escreverSelecao(container, [...new Set([...preservados, ...marcados])]);
    container.closest("form").submit();
}

function limpar(container) {
    escreverSelecao(container, []);
    container.closest("form").submit();
}

/** Troca os inputs escondidos que carregam a seleção no envio do formulário. */
function escreverSelecao(container, valores) {
    container.querySelectorAll(".filtro-coluna-atual").forEach((i) => i.remove());
    const coluna = container.dataset.coluna;
    valores.forEach((v) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = coluna;
        input.value = v;
        input.className = "filtro-coluna-atual";
        container.appendChild(input);
    });
}

function escapar(texto) {
    return String(texto).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
}
