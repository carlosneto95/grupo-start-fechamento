function inicializar() {
    document.getElementById("btn-sincronizar")
        .addEventListener("click", () => iniciar(false));
    document.getElementById("btn-forcar")
        .addEventListener("click", () => {
            const ano = document.getElementById("ano").value;
            const msg = `Isso vai rebuscar TODAS as contas de ${ano}, uma a uma, ` +
                        `e pode levar mais de 20 minutos. Continuar?`;
            if (confirm(msg)) iniciar(true);
        });

    verificarStatus(); // caso já exista algo rodando ao abrir a tela
}

function botoes() {
    return [document.getElementById("btn-sincronizar"), document.getElementById("btn-forcar")];
}

async function iniciar(forcar) {
    botoes().forEach((b) => (b.disabled = true));

    const corpo = {
        empresa: document.getElementById("empresa").value,
        ano: parseInt(document.getElementById("ano").value, 10),
        forcar: forcar,
    };

    try {
        const resp = await fetch("/extracao/iniciar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(corpo),
        });
        const dados = await resp.json();
        if (!dados.ok) {
            alert(dados.mensagem);
            botoes().forEach((b) => (b.disabled = false));
            return;
        }
        document.getElementById("resultado").innerHTML = "";
        document.getElementById("painel-progresso").hidden = false;
        acompanhar();
    } catch (e) {
        alert("Não consegui iniciar: " + e.message);
        botoes().forEach((b) => (b.disabled = false));
    }
}

function acompanhar() {
    verificarStatus();
    const timer = setInterval(async () => {
        const rodando = await verificarStatus();
        if (!rodando) clearInterval(timer);
    }, 2000);
}

function montarResultado(estado) {
    const r = estado.resumo;
    let html = `<p>Concluído em ${estado.terminado_em}.</p><ul>` +
        `<li>Contas encontradas no período: <strong>${r.encontradas}</strong></li>` +
        `<li>Novas gravadas: <strong>${r.novas}</strong></li>` +
        `<li>Atualizadas: <strong>${r.atualizadas}</strong></li>` +
        `<li>Sem mudança: <strong>${r.sem_mudanca}</strong></li></ul>`;

    if (r.mudancas && r.mudancas.length) {
        const itens = r.mudancas.map((m) => {
            const difs = m.diferencas
                .map((d) => `${d.campo}: <em>${d.de ?? "vazio"}</em> &rarr; <strong>${d.para ?? "vazio"}</strong>`)
                .join("; ");
            return `<li>${m.fornecedor || m.id} — ${difs}</li>`;
        }).join("");
        const extra = r.mudancas_total > r.mudancas.length
            ? `<p class="legenda">Mostrando ${r.mudancas.length} de ${r.mudancas_total} alterações.</p>` : "";
        html += `<h3>O que mudou no ERP</h3><ul>${itens}</ul>${extra}`;
    } else if (r.atualizadas === 0 && r.novas === 0) {
        html += `<p>Nada mudou no ERP desde a última sincronização.</p>`;
    }

    html += `<p><a href="/contas-pagar">Ver os dados em Contas a Pagar &rarr;</a></p>`;
    return html;
}

async function verificarStatus() {
    let estado;
    try {
        const resp = await fetch("/extracao/status");
        estado = await resp.json();
    } catch {
        return true; // tenta de novo no próximo ciclo
    }

    if (!estado.rodando && !estado.resumo && !estado.erro) return false;

    document.getElementById("painel-progresso").hidden = false;
    document.getElementById("progresso-etapa").textContent = estado.etapa || "";

    const barra = document.getElementById("barra");
    const texto = document.getElementById("progresso-texto");
    if (estado.total > 0 && estado.feitos > 0) {
        barra.max = estado.total;
        barra.value = estado.feitos;
        const restantes = Math.max(estado.total - estado.feitos, 0);
        texto.textContent = `${estado.feitos} de ${estado.total} contas` +
            (estado.rodando && restantes > 0
                ? ` — faltam cerca de ${Math.max(1, Math.ceil(restantes * 1.1 / 60))} min` : "");
    } else if (estado.total > 0) {
        barra.removeAttribute("value");
        texto.textContent = `${estado.total} contas encontradas até agora...`;
    } else {
        barra.removeAttribute("value");
        texto.textContent = "";
    }

    const resultado = document.getElementById("resultado");
    if (estado.erro) {
        resultado.innerHTML = `<p class="aviso">Erro: ${estado.erro}</p>`;
    } else if (estado.resumo) {
        resultado.innerHTML = montarResultado(estado);
    }

    if (!estado.rodando) {
        botoes().forEach((b) => (b.disabled = false));
        if (estado.total > 0) barra.value = barra.max;
    }
    return estado.rodando;
}

document.addEventListener("DOMContentLoaded", inicializar);
