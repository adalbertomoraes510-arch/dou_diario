const $ = (id) => document.getElementById(id);

let ambiente = null;
let processosCache = [];

function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function fmt(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("pt-BR");
  } catch (_) {
    return String(v);
  }
}

function pill(status) {
  const s = String(status || "SEM_STATUS");
  const up = s.toUpperCase();
  let cls = "neutral";
  if (up.includes("SUCESS") || up.includes("ATIVO") || up === "OK") cls = "ok";
  else if (up.includes("ERRO") || up.includes("FALHA")) cls = "bad";
  else if (up.includes("PEND") || up.includes("ATEN")) cls = "warn";
  return `<span class="pill ${cls}">${esc(s)}</span>`;
}

function toast(msg, tempo=5000) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), tempo);
}

async function api(url, options={}) {
  const r = await fetch(url, {
    headers: {"Content-Type":"application/json", ...(options.headers || {})},
    ...options
  });

  let payload = null;
  try { payload = await r.json(); } catch (_) {}

  if (!r.ok) {
    throw new Error(payload?.detail || `Erro HTTP ${r.status}`);
  }
  return payload;
}

function renderCards(s) {
  ambiente = s.ambiente;
  const badge = $("envBadge");
  badge.textContent = s.ambiente;
  badge.className = `badge ${s.ambiente === "PROD" ? "prod" : "dev"}`;

  $("subtitulo").textContent =
    `${s.root} • atualizado ${fmt(s.agora)}`;

  const p = s.processos || {};
  $("processosStatus").innerHTML =
    `${p.ativos_incrementais || 0} ativos`;
  $("processosMeta").innerHTML =
    `${p.total || 0} total • ${p.pendentes || 0} pendentes<br>` +
    `Última data DOU: ${esc(p.ultima_data_dou || "—")}`;

  const inc = s.etapas?.dou_incremental || {};
  $("incrementalStatus").innerHTML = pill(inc.status);
  $("incrementalMeta").innerHTML =
    `Data: ${esc(inc.data_execucao || "—")}<br>` +
    `Resultados: ${esc(inc.total_resultados ?? "—")}`;

  const syn = s.etapas?.sincronizacao_processos || {};
  $("syncStatus").innerHTML = pill(syn.status);
  $("syncMeta").innerHTML =
    `Atualizado: ${esc(fmt(syn.modificado_em))}`;

  const anvisa = s.etapas?.anvisa || {};
  $("anvisaStatus").innerHTML = pill(anvisa.status);
  $("anvisaMeta").innerHTML =
    `Evidência: ${esc(anvisa.arquivo ? "sim" : "não")}<br>` +
    `${esc(fmt(anvisa.modificado_em))}`;

  const git = s.git || {};
  $("gitStatus").innerHTML =
    git.limpo ? `<span class="status-ok">Limpo</span>` :
                `<span class="status-warn">Alterações locais</span>`;
  $("gitMeta").innerHTML =
    `${esc(git.branch || "—")} • ${esc(git.commit || "—")}<br>` +
    `origin/main: ${esc(git.origin_main || "—")}`;

  const pend = Number(p.pendentes || 0);
  const gitDirty = !git.limpo;
  let geral = "OK";
  if (pend > 0) geral = "ATENÇÃO";
  if (gitDirty && s.ambiente === "PROD") geral = "ATENÇÃO";

  $("geralStatus").innerHTML =
    geral === "OK"
      ? `<span class="status-ok">Operacional</span>`
      : `<span class="status-warn">${geral}</span>`;

  $("geralMeta").innerHTML =
    `${s.possivel_execucao_hoje ? "Há evidência de processamento hoje" : "Sem evidência de execução hoje"}<br>` +
    `${s.execucao_painel_atual?.status || "Sem execução pelo painel"}`;

  const run = s.execucao_painel_atual;
  $("runningBadge").textContent =
    run && ["AGENDADO","EM_EXECUCAO"].includes(run.status)
      ? `${run.status}: ${run.titulo}`
      : "Sem execução ativa";
}

function renderAlerts(alertas) {
  const el = $("alerts");
  el.innerHTML = (alertas || [])
    .map(a => `<div class="alert ${esc(a.nivel)}">${esc(a.mensagem)}</div>`)
    .join("");
}

function renderProcessos(itens) {
  processosCache = itens || [];
  filtrarProcessos();
}

function filtrarProcessos() {
  const q = ($("processSearch").value || "").toLowerCase().trim();

  const rows = processosCache.filter(p => {
    const blob = [
      p.processo,
      p.status,
      p.observacao,
      p.ultima_data_dou_processada,
    ].join(" ").toLowerCase();
    return !q || blob.includes(q);
  });

  $("processTable").innerHTML = rows.map(p => `
    <tr>
      <td><strong>${esc(p.processo)}</strong></td>
      <td>${pill(p.status)}</td>
      <td>${p.historico_revisado ? "Sim" : "Não"}</td>
      <td>${esc(p.ultima_data_dou_processada || "—")}</td>
      <td>${esc(fmt(p.ultima_execucao_incremental_em))}</td>
      <td>${esc(p.observacao || "—")}</td>
    </tr>
  `).join("");
}

function renderExecucoes(itens) {
  const el = $("execList");

  if (!itens?.length) {
    el.innerHTML = `<div class="list-item">Nenhuma execução iniciada pelo painel.</div>`;
    return;
  }

  el.innerHTML = itens.map(x => `
    <div class="list-item ${x.log_path ? "clickable" : ""}"
         data-log="${esc(x.log_path || "")}">
      <div class="list-title">
        ${pill(x.status)} ${esc(x.titulo || x.acao)}
      </div>
      <div class="list-meta">
        ${esc(x.criado_em || "—")} • job ${esc(x.id || "—")}<br>
        código: ${esc(x.codigo_saida ?? "—")} • ${esc(x.log_path || "")}
      </div>
    </div>
  `).join("");

  el.querySelectorAll("[data-log]").forEach(node => {
    node.addEventListener("click", () => {
      const p = node.dataset.log;
      if (p) abrirLog(p);
    });
  });
}

function renderLogs(itens) {
  const el = $("logList");

  el.innerHTML = (itens || []).map(x => `
    <div class="list-item clickable" data-path="${esc(x.path)}">
      <div class="list-title">${esc(x.nome)}</div>
      <div class="list-meta">
        ${esc(fmt(x.modificado_em))} • ${esc(x.tamanho)} bytes<br>
        ${esc(x.path)}
      </div>
    </div>
  `).join("");

  el.querySelectorAll("[data-path]").forEach(node => {
    node.addEventListener("click", () => abrirLog(node.dataset.path));
  });
}

async function abrirLog(path) {
  try {
    const r = await api(`/api/logs/conteudo?path=${encodeURIComponent(path)}`);
    $("logTitle").textContent = r.path;
    $("logViewer").textContent =
      (r.truncado ? "[conteúdo truncado: exibindo final do arquivo]\n\n" : "") +
      r.conteudo;
  } catch (e) {
    toast(e.message);
  }
}

const ETAPAS_ESPERADAS = [
  ["SINCRONIZACAO_PROCESSOS", "Sincronização de processos"],
  ["ANVISA_INCREMENTAL", "Pesquisa Anvisa"],
  ["INLABS", "Consulta INLABS"],
  ["CONTINGENCIA_V7", "Contingência V7 (se necessária)"],
  ["EMAIL_DOU_DIARIO", "Envio do e-mail"]
];
const ROTULOS_ETAPAS = Object.fromEntries(ETAPAS_ESPERADAS);
function detalhesTexto(detalhes) {
  if (!detalhes || typeof detalhes !== "object") return "—";
  const campos = Object.entries(detalhes).filter(([k,v]) =>
    v !== null && v !== undefined && k !== "destinatarios" && k !== "email" && k !== "senha"
  );
  return campos.length ? campos.map(([k,v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ").slice(0,800) : "—";
}
function renderAtividadesExecucao(execucao) {
  const corpo = $("execucaoAtividades");
  corpo.replaceChildren();
  const atividades = Array.isArray(execucao?.atividades) ? execucao.atividades : [];
  const mapa = new Map(atividades.map(a => [a.etapa, a]));
  const linhas = [
    ...ETAPAS_ESPERADAS.map(([id,nome]) => ({...mapa.get(id), etapa:id, nome,
      status:mapa.get(id)?.status || (execucao ? "SEM_REGISTRO" : "AGUARDANDO")})),
    ...atividades.filter(a => !ROTULOS_ETAPAS[a.etapa]).map(a => ({...a,nome:a.etapa}))
  ];
  for (const a of linhas) {
    const tr = document.createElement("tr");
    const nome = document.createElement("td");nome.textContent = a.nome || a.etapa;
    const status = document.createElement("td");
    const s = document.createElement("span");s.className = "stage-status stage-" + String(a.status).toLowerCase();
    s.textContent = a.status || "AGUARDANDO";status.appendChild(s);
    const horario = document.createElement("td");horario.textContent = a.registrado_em ? fmt(a.registrado_em) : "—";
    const obs = document.createElement("td");obs.textContent = detalhesTexto(a.detalhes);
    tr.append(nome,status,horario,obs);corpo.appendChild(tr);
  }
}
function atualizarIndicadoresExecucao(execucao) {
  const inicio = execucao?.iniciado_em;
  const fim = execucao?.finalizado_em || execucao?.finalizada_em;
  const segundos = inicio ? Math.max(0,Math.floor(((fim ? Date.parse(fim) : Date.now())-Date.parse(inicio))/1000) || 0) : 0;
  const pad = n => String(n).padStart(2,"0");
  $("execucaoTempo").textContent = `${pad(Math.floor(segundos/3600))}:${pad(Math.floor((segundos%3600)/60))}:${pad(segundos%60)}`;
  $("execucaoInicio").textContent = inicio ? `Início: ${fmt(inicio)}` : "Ainda não iniciada";
  $("execucaoGeralBadge").textContent = execucao?.status || "Sem execução";
  const n = Number(execucao?.total_atividades_registradas || 0);
  const f = Number(execucao?.atividades_finalizadas || 0);
  $("execucaoPercentual").textContent = n ? `${f}/${n}` : "—";
  $("execucaoBarra").value = n ? Math.min(100,100*f/n) : 0;
  const email = (execucao?.atividades || []).find(x => x.etapa === "EMAIL_DOU_DIARIO");
  $("execucaoEmail").textContent = email?.status || "Sem confirmação";
  $("execucaoEmailDetalhes").textContent = email?.registrado_em ? `Último evento: ${fmt(email.registrado_em)}` : "Envio não confirmado nesta execução";
}
async function refresh() {
  try {
    const [s, p, e, l] = await Promise.all([
      api("/api/status"),
      api("/api/processos"),
      api("/api/execucoes?limite=30"),
      api("/api/logs?limite=60"),
    ]);

    renderCards(s);
    renderAlerts(s.alertas);
    renderProcessos(p.itens);
    renderExecucoes(e.itens);
    renderAtividadesExecucao(
      Array.isArray(e.itens) && e.itens.length > 0
        ? e.itens[0]
        : null
    );
    atualizarIndicadoresExecucao(
      Array.isArray(e.itens) && e.itens.length > 0
        ? e.itens[0]
        : null
    );
    renderLogs(l.itens);
  } catch (e) {
    toast(e.message, 8000);
  }
}

async function executar(acao, confirmacao, data_referencia=null, forcar=false) {
  if (!confirmacao?.trim()) {
    toast(`Digite ${ambiente || "o ambiente"} para confirmar.`);
    return;
  }

  const texto =
    `Confirmar execução de "${acao}" no ambiente ${ambiente}?`;

  if (!window.confirm(texto)) return;

  try {
    const r = await api("/api/executar", {
      method: "POST",
      body: JSON.stringify({
        acao,
        confirmacao,
        data_referencia,
        forcar,
      }),
    });

    toast(`Execução aceita. Job ${r.execucao.id}`);
    await refresh();
  } catch (e) {
    toast(e.message, 10000);
  }
}

$("refreshBtn").addEventListener("click", refresh);
$("processSearch").addEventListener("input", filtrarProcessos);

$("runHoje").addEventListener("click", () => {
  executar(
    "ORQUESTRADOR_HOJE",
    $("confirmHoje").value,
    null,
    $("forceHoje").checked,
  );
});

$("runIncremental").addEventListener("click", () => {
  executar(
    "INCREMENTAL_DOU",
    $("confirmIncremental").value,
    $("dataIncremental").value || null,
    false,
  );
});

$("runSync").addEventListener("click", () => {
  executar(
    "SINCRONIZAR_PROCESSOS",
    $("confirmSync").value,
    null,
    false,
  );
});

$("clearLog").addEventListener("click", () => {
  $("logTitle").textContent = "Visualizador";
  $("logViewer").textContent = "Selecione um log para visualizar.";
});

const hoje = new Date().toLocaleDateString("en-CA");
$("dataIncremental").value = hoje;

refresh();
setInterval(refresh, 5000);
