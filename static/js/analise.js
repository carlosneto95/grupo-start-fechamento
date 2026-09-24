// Dashboard de análise: slicers que filtram ao clicar e árvore de gastos
// que expande/recolhe nível a nível.

document.addEventListener("DOMContentLoaded", () => {
    inicializarSlicers();
    inicializarArvore();
});

/* ---------------- Slicers ---------------- */

function inicializarSlicers() {
    const form = document.getElementById("form-analise");
    if (!form) return;

    // Clicar num item aplica o filtro na hora, sem botão "Filtrar" —
    // é o comportamento de slicer que se espera do Excel.
    form.querySelectorAll(".slicer-item input").forEach((chk) => {
        chk.addEventListener("change", () => form.submit());
    });

    form.querySelectorAll(".slicer-limpar").forEach((botao) => {
        botao.addEventListener("click", () => {
            const slicer = botao.closest(".slicer");
            const marcados = [...slicer.querySelectorAll("input:checked")];
            if (!marcados.length) return;
            marcados.forEach((c) => (c.checked = false));
            form.submit();
        });
    });
}

/* ---------------- Árvore de gastos ---------------- */

function inicializarArvore() {
    document.querySelectorAll(".expandir-linha").forEach((botao) => {
        botao.addEventListener("click", () => alternarLinha(botao));
    });
}

function alternarLinha(botao) {
    const linha = botao.closest("tr");
    const id = linha.dataset.id;
    if (!id) return;

    const abrindo = botao.textContent === "+";
    botao.textContent = abrindo ? "−" : "+";

    if (abrindo) {
        // Abre só os filhos diretos; netos continuam recolhidos.
        filhosDiretos(id).forEach((f) => (f.hidden = false));
    } else {
        // Ao fechar, esconde toda a descendência e reseta os botões de baixo,
        // senão reabrir mostraria netos que o usuário já tinha fechado.
        descendentes(id).forEach((f) => {
            f.hidden = true;
            const b = f.querySelector(".expandir-linha");
            if (b && !b.disabled) b.textContent = "+";
        });
    }
}

function filhosDiretos(id) {
    return [...document.querySelectorAll(`tr[data-pai="${id}"]`)];
}

function descendentes(id) {
    const diretos = filhosDiretos(id);
    return diretos.concat(...diretos.map((f) => (f.dataset.id ? descendentes(f.dataset.id) : [])));
}
