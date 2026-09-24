// Tela "Sincronizar com o Tiny": dispara o job único (despesas + notas) e
// acompanha o progresso.
//
// Regras desta tela (CLAUDE.md e Fase 1):
//   - nada de alert()/confirm(): congelam a aba. Aviso vai na própria tela e
//     a confirmação do modo forçado é um segundo clique no mesmo botão;
//   - nada de innerHTML com dado vindo do Tiny (nome de fornecedor, texto de
//     erro): tudo entra por textContent, então um nome com "<script>" é só
//     texto na tela;
//   - endereços vêm do servidor (data-* com url_for), nunca fixos: em
//     produção o sistema roda sob um prefixo.

const bloco = () => document.querySelector(".bloco-extracao");
const botoes = () => [document.getElementById("btn-sincronizar"), document.getElementById("btn-forcar")];
const TIPO = { contas: "despesas", notas: "receitas" };

let confirmacaoPendente = null;

function avisar(texto) {
    const aviso = document.getElementById("aviso-inicio");
    aviso.textContent = texto;
    aviso.hidden = !texto;
}

function inicializar() {
    if (!bloco()) return;
    document.getElementById("btn-sincronizar").addEventListener("click", () => iniciar(false));

    // Confirmação em dois cliques: o primeiro arma, o segundo (em até 8 s) dispara.
    const forcar = document.getElementById("btn-forcar");
    const rotuloOriginal = forcar.textContent;
    forcar.addEventListener("click", () => {
        if (confirmacaoPendente) {
            clearTimeout(confirmacaoPendente);
            confirmacaoPendente = null;
            forcar.textContent = rotuloOriginal;
            iniciar(true);
            return;
        }
        forcar.textContent = "Clique de novo para confirmar (rebusca tudo)";
        confirmacaoPendente = setTimeout(() => {
            confirmacaoPendente = null;
            forcar.textContent = rotuloOriginal;
        }, 8000);
    });

    verificarStatus(); // caso já exista algo rodando ao abrir a tela
}

async function iniciar(forcar) {
    avisar("");
    botoes().forEach((b) => (b.disabled = true));
    const corpo = {
        empresa: document.getElementById("empresa").value,
        ano: parseInt(document.getElementById("ano").value, 10),
        forcar,
    };
    try {
        // postarJson (csrf.js): leva o token CSRF no cabeçalho.
        const resp = await postarJson(bloco().dataset.iniciar, corpo);
        const dados = await resp.json();
        if (!dados.ok) {
            avisar(dados.mensagem);
            botoes().forEach((b) => (b.disabled = false));
            return;
        }
        document.getElementById("resultado").replaceChildren();
        document.getElementById("painel-progresso").hidden = false;
        acompanhar();
    } catch (e) {
        avisar("Não consegui iniciar: " + e.message);
        botoes().forEach((b) => (b.disabled = false));
    }
}

function acompanhar() {
    verificarStatus();
    const timer = setInterval(async () => {
        if (!(await verificarStatus())) clearInterval(timer);
    }, 2000);
}

// Monta um elemento com texto — atalho para não cair na tentação do innerHTML.
function el(tag, texto, classe) {
    const e = document.createElement(tag);
    if (texto !== undefined) e.textContent = texto;
    if (classe) e.className = classe;
    return e;
}

function montarResultado(estado) {
    const caixa = document.getElementById("resultado");
    caixa.replaceChildren(el("p", `Concluído em ${(estado.terminado_em || "").replace("T", " ")}.`));

    const lista = el("ul");
    for (const r of estado.resultados) {
        const rotulo = `${r.empresa} · ${TIPO[r.tipo] || r.tipo}: `;
        const texto = r.status === "ok"
            ? `${r.encontradas ?? 0} no período, ${r.novas ?? 0} novas, ${r.atualizadas ?? 0} atualizadas`
            : `ERRO — ${r.erro}`;
        lista.append(el("li", rotulo + texto, r.status === "ok" ? "" : "aviso"));
    }
    caixa.append(lista);

    const comMudanca = estado.resultados.filter((r) => r.mudancas && r.mudancas.length);
    for (const r of comMudanca) {
        caixa.append(el("h3", `O que mudou no ERP — ${r.empresa}`));
        const ul = el("ul");
        for (const m of r.mudancas) {
            const difs = m.diferencas
                .map((d) => `${d.campo}: ${d.de ?? "vazio"} → ${d.para ?? "vazio"}`)
                .join("; ");
            ul.append(el("li", `${m.fornecedor || m.id} — ${difs}`));
        }
        caixa.append(ul);
        if (r.mudancas_total > r.mudancas.length) {
            caixa.append(el("p", `Mostrando ${r.mudancas.length} de ${r.mudancas_total} alterações.`, "legenda"));
        }
    }
}

async function verificarStatus() {
    let estado;
    try {
        const resp = await fetch(bloco().dataset.status);
        estado = await resp.json();
    } catch {
        return true; // tenta de novo no próximo ciclo
    }
    if (!estado.rodando && !estado.resultados.length && !estado.erro) return false;

    document.getElementById("painel-progresso").hidden = false;
    const onde = estado.empresa ? `${estado.empresa} · ${TIPO[estado.tipo] || ""} — ` : "";
    document.getElementById("progresso-etapa").textContent = onde + (estado.etapa || "");

    const barra = document.getElementById("barra");
    const texto = document.getElementById("progresso-texto");
    if (estado.total > 0 && estado.feitos > 0) {
        barra.max = estado.total;
        barra.value = estado.feitos;
        const restantes = Math.max(estado.total - estado.feitos, 0);
        texto.textContent = `${estado.feitos} de ${estado.total}` +
            (estado.rodando && restantes > 0
                ? ` — faltam cerca de ${Math.max(1, Math.ceil(restantes * 1.1 / 60))} min` : "");
    } else {
        barra.removeAttribute("value");
        texto.textContent = estado.total > 0 ? `${estado.total} encontradas até agora...` : "";
    }

    if (estado.erro) {
        document.getElementById("resultado").replaceChildren(el("p", "Erro: " + estado.erro, "aviso"));
    } else if (!estado.rodando && estado.resultados.length) {
        montarResultado(estado);
    }

    if (!estado.rodando) {
        botoes().forEach((b) => (b.disabled = false));
        if (estado.total > 0) barra.value = barra.max;
    }
    return estado.rodando;
}

document.addEventListener("DOMContentLoaded", inicializar);
