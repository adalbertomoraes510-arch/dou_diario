# ============================================================
# RUNNER — Mapear Busca Avançada DOU para Resolver Link Moderno
# Projeto Informativos / DOU
#
# Objetivo:
# - Abrir o portal do DOU.
# - Executar o mesmo caminho manual da Pesquisa Avançada.
# - Registrar cada clique/preenchimento.
# - Mapear inputs, radios, checkboxes, botões, links e seletores.
# - Capturar os links modernos /web/dou/-/ retornados.
# - NÃO altera base, match, e-mail, relatório ou orquestrador.
#
# Saídas:
# backend/data/dou/mapeamentos/busca_avancada/
#   - JSON técnico
#   - TXT legível
#   - screenshots por etapa
# ============================================================

import asyncio
import datetime
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÃO DO TESTE
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 15)

TITULO_OFICIAL = "DESPACHO DO DIRETOR PRESIDENTE Nº 71-E, DE 14 DE MAIO DE 2026"

URL_INICIAL = "https://www.in.gov.br/inicio"

HEADLESS = False

ROOT_DIR = Path(__file__).resolve().parents[2]

SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "mapeamentos" / "busca_avancada"
SCREENSHOT_DIR = SAIDA_DIR / "screenshots"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

ARQ_JSON = SAIDA_DIR / f"mapeamento_busca_avancada_dou_{DATA_EXECUCAO.isoformat()}.json"
ARQ_TXT = SAIDA_DIR / f"mapeamento_busca_avancada_dou_{DATA_EXECUCAO.isoformat()}.txt"


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalizar_texto(valor) -> str:
    texto = str(valor or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def data_br(data: datetime.date) -> str:
    return data.strftime("%d/%m/%Y")


def data_url(data: datetime.date) -> str:
    return data.strftime("%d-%m-%Y")


def query_url_direta(titulo: str, data: datetime.date) -> str:
    q = quote_plus(titulo)
    d = data_url(data)
    return (
        "https://www.in.gov.br/consulta/-/buscar/dou"
        f"?q={q}"
        "&s=todos"
        "&exactDate=personalizado"
        "&sortType=0"
        f"&publishFrom={d}"
        f"&publishTo={d}"
    )


async def coletar_mapa_dom(page) -> dict:
    """
    Coleta um inventário técnico dos elementos úteis da página atual.
    """
    return await page.evaluate(
        """
        () => {
            function visivel(el) {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return !!(r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none');
            }

            function resumo(el, idx) {
                const r = el.getBoundingClientRect();
                const attrs = {};
                for (const a of el.attributes || []) attrs[a.name] = a.value;

                return {
                    index: idx,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    value: el.value || el.getAttribute('value') || '',
                    checked: !!el.checked,
                    placeholder: el.getAttribute('placeholder') || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    role: el.getAttribute('role') || '',
                    text: (el.innerText || el.textContent || '').trim().slice(0, 300),
                    href: el.href || el.getAttribute('href') || '',
                    class: el.className || '',
                    visible: visivel(el),
                    box: {
                        x: Math.round(r.x),
                        y: Math.round(r.y),
                        w: Math.round(r.width),
                        h: Math.round(r.height)
                    },
                    attrs
                };
            }

            const selectors = {
                inputs: Array.from(document.querySelectorAll('input')).map(resumo),
                buttons: Array.from(document.querySelectorAll('button, input[type=button], input[type=submit]')).map(resumo),
                labels: Array.from(document.querySelectorAll('label')).map(resumo),
                links: Array.from(document.querySelectorAll('a[href]')).map(resumo),
                selects: Array.from(document.querySelectorAll('select')).map(resumo),
                radios: Array.from(document.querySelectorAll('input[type=radio]')).map(resumo),
                checkboxes: Array.from(document.querySelectorAll('input[type=checkbox]')).map(resumo)
            };

            return {
                url: location.href,
                title: document.title,
                body_text_preview: (document.body.innerText || '').trim().slice(0, 3000),
                selectors
            };
        }
        """
    )


async def salvar_etapa(page, etapas: list, nome: str, descricao: str, extra: dict | None = None):
    screenshot_path = SCREENSHOT_DIR / f"{len(etapas)+1:02d}_{nome}.png"

    try:
        await page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        screenshot_path = None

    mapa_dom = await coletar_mapa_dom(page)

    etapa = {
        "ordem": len(etapas) + 1,
        "nome": nome,
        "descricao": descricao,
        "url": page.url,
        "titulo_pagina": await page.title(),
        "screenshot": str(screenshot_path) if screenshot_path else "",
        "extra": extra or {},
        "dom": mapa_dom,
    }

    etapas.append(etapa)

    print("=" * 80)
    print(f"ETAPA {etapa['ordem']}: {nome}")
    print(descricao)
    print(f"URL: {page.url}")
    print(f"Screenshot: {etapa['screenshot']}")
    print("=" * 80)


async def tentar_click(page, descricao: str, tentativas: list):
    erros = []

    for tentativa in tentativas:
        tipo = tentativa["tipo"]
        alvo = tentativa["alvo"]

        try:
            if tipo == "text":
                await page.get_by_text(alvo, exact=tentativa.get("exact", False)).click(timeout=5000)
            elif tipo == "role_button":
                await page.get_by_role("button", name=alvo).click(timeout=5000)
            elif tipo == "label":
                await page.get_by_label(alvo).click(timeout=5000)
            elif tipo == "locator":
                await page.locator(alvo).first().click(timeout=5000)
            elif tipo == "evaluate_text":
                await page.evaluate(
                    """
                    (texto) => {
                        const alvo = texto.toLowerCase();
                        const els = Array.from(document.querySelectorAll('button, a, label, span, div'));
                        const el = els.find(e => (e.innerText || e.textContent || '').trim().toLowerCase().includes(alvo));
                        if (!el) throw new Error('Elemento por texto não encontrado: ' + texto);
                        el.click();
                    }
                    """,
                    alvo,
                )
            else:
                continue

            print(f"[OK] {descricao} | estratégia={tipo} | alvo={alvo}")
            return {"ok": True, "estrategia": tipo, "alvo": str(alvo), "erros": erros}

        except Exception as erro:
            erros.append({
                "estrategia": tipo,
                "alvo": str(alvo),
                "erro": str(erro),
            })

    print(f"[FALHA] {descricao}")
    return {"ok": False, "estrategia": "", "alvo": "", "erros": erros}


async def tentar_check(page, descricao: str, label_texto: str):
    erros = []

    estrategias = [
        ("label", label_texto),
        ("text", label_texto),
        ("evaluate_label", label_texto),
    ]

    for tipo, alvo in estrategias:
        try:
            if tipo == "label":
                loc = page.get_by_label(alvo)
                await loc.check(timeout=5000)
            elif tipo == "text":
                await page.get_by_text(alvo, exact=True).click(timeout=5000)
            elif tipo == "evaluate_label":
                await page.evaluate(
                    """
                    (texto) => {
                        const alvo = texto.toLowerCase();
                        const labels = Array.from(document.querySelectorAll('label'));
                        const label = labels.find(l => (l.innerText || l.textContent || '').trim().toLowerCase().includes(alvo));
                        if (label) {
                            label.click();
                            return;
                        }

                        const els = Array.from(document.querySelectorAll('input[type=radio], input[type=checkbox]'));
                        const found = els.find(i => {
                            const id = i.id || '';
                            const name = i.name || '';
                            const value = i.value || '';
                            return (id + ' ' + name + ' ' + value).toLowerCase().includes(alvo);
                        });
                        if (!found) throw new Error('Radio/checkbox não encontrado: ' + texto);
                        found.click();
                    }
                    """,
                    alvo,
                )

            print(f"[OK] {descricao} | {label_texto} | estratégia={tipo}")
            return {"ok": True, "estrategia": tipo, "alvo": label_texto, "erros": erros}

        except Exception as erro:
            erros.append({
                "estrategia": tipo,
                "alvo": label_texto,
                "erro": str(erro),
            })

    print(f"[FALHA] {descricao} | {label_texto}")
    return {"ok": False, "estrategia": "", "alvo": label_texto, "erros": erros}


async def preencher_campo_busca(page, titulo: str):
    erros = []

    # Primeiro tenta pelo input de maior largura visível, antes dos campos de data.
    try:
        resultado = await page.evaluate(
            """
            (valor) => {
                function visivel(el) {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return !!(r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none');
                }

                const inputs = Array.from(document.querySelectorAll('input'))
                    .filter(i => visivel(i))
                    .filter(i => {
                        const type = (i.getAttribute('type') || 'text').toLowerCase();
                        return ['text', 'search', ''].includes(type);
                    })
                    .map(i => {
                        const r = i.getBoundingClientRect();
                        return { el: i, w: r.width, y: r.y, id: i.id || '', name: i.name || '', placeholder: i.placeholder || '' };
                    })
                    .sort((a, b) => b.w - a.w);

                if (!inputs.length) throw new Error('Nenhum input texto visível encontrado.');

                const escolhido = inputs[0];
                escolhido.el.focus();
                escolhido.el.value = '';
                escolhido.el.dispatchEvent(new Event('input', { bubbles: true }));
                escolhido.el.value = valor;
                escolhido.el.dispatchEvent(new Event('input', { bubbles: true }));
                escolhido.el.dispatchEvent(new Event('change', { bubbles: true }));

                return {
                    id: escolhido.id,
                    name: escolhido.name,
                    placeholder: escolhido.placeholder,
                    width: escolhido.w,
                    y: escolhido.y
                };
            }
            """,
            titulo,
        )

        print(f"[OK] Campo de pesquisa preenchido | {resultado}")
        return {"ok": True, "estrategia": "maior_input_texto_visivel", "detalhes": resultado, "erros": erros}

    except Exception as erro:
        erros.append({"estrategia": "maior_input_texto_visivel", "erro": str(erro)})

    print("[FALHA] preencher campo de pesquisa")
    return {"ok": False, "estrategia": "", "detalhes": {}, "erros": erros}


async def preencher_data_por_label_ou_posicao(page, label: str, valor: str):
    erros = []

    try:
        await page.get_by_label(label).fill(valor, timeout=5000)
        print(f"[OK] Data {label} preenchida por label: {valor}")
        return {"ok": True, "estrategia": "get_by_label", "label": label, "valor": valor, "erros": erros}
    except Exception as erro:
        erros.append({"estrategia": "get_by_label", "erro": str(erro)})

    try:
        resultado = await page.evaluate(
            """
            ({label, valor}) => {
                function visivel(el) {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return !!(r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none');
                }

                const textoAlvo = label.toLowerCase();
                const all = Array.from(document.querySelectorAll('body *'));
                const labelEl = all.find(e => (e.innerText || e.textContent || '').trim().toLowerCase() === textoAlvo);

                const inputs = Array.from(document.querySelectorAll('input')).filter(visivel);

                let escolhido = null;

                if (labelEl) {
                    const rb = labelEl.getBoundingClientRect();
                    let menorDist = Infinity;

                    for (const input of inputs) {
                        const r = input.getBoundingClientRect();
                        if (r.y < rb.y) continue;
                        const dist = Math.abs(r.y - rb.y) + Math.abs(r.x - rb.x);
                        if (dist < menorDist) {
                            menorDist = dist;
                            escolhido = input;
                        }
                    }
                }

                if (!escolhido) {
                    const candidatos = inputs.filter(i => {
                        const r = i.getBoundingClientRect();
                        return r.width >= 80 && r.width <= 250;
                    });
                    escolhido = label.toLowerCase().includes('fim') ? candidatos[candidatos.length - 1] : candidatos[0];
                }

                if (!escolhido) throw new Error('Input de data não encontrado para ' + label);

                escolhido.focus();
                escolhido.value = '';
                escolhido.dispatchEvent(new Event('input', { bubbles: true }));
                escolhido.value = valor;
                escolhido.dispatchEvent(new Event('input', { bubbles: true }));
                escolhido.dispatchEvent(new Event('change', { bubbles: true }));

                return {
                    id: escolhido.id || '',
                    name: escolhido.name || '',
                    value: escolhido.value || '',
                    type: escolhido.type || '',
                    placeholder: escolhido.placeholder || ''
                };
            }
            """,
            {"label": label, "valor": valor},
        )

        print(f"[OK] Data {label} preenchida por avaliação DOM: {resultado}")
        return {"ok": True, "estrategia": "evaluate_posicao", "label": label, "valor": valor, "detalhes": resultado, "erros": erros}

    except Exception as erro:
        erros.append({"estrategia": "evaluate_posicao", "erro": str(erro)})

    print(f"[FALHA] preencher data {label}")
    return {"ok": False, "estrategia": "", "label": label, "valor": valor, "erros": erros}


async def coletar_links_modernos(page) -> list[dict]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            texto: (a.innerText || a.textContent || '').trim(),
            href: a.href
        })).filter(x => x.href && x.href.includes('/web/dou/-/'))
        """
    )


# ============================================================
# EXECUÇÃO
# ============================================================

async def main():
    etapas = []
    acoes = []

    print("=" * 80)
    print("MAPEAMENTO BUSCA AVANÇADA DOU")
    print("=" * 80)
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Título oficial: {TITULO_OFICIAL}")
    print(f"URL inicial: {URL_INICIAL}")
    print("=" * 80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        await page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await salvar_etapa(page, etapas, "inicio_carregado", "Portal inicial carregado.")

        acao = await tentar_click(
            page,
            "Abrir Pesquisa Avançada",
            [
                {"tipo": "text", "alvo": "PESQUISA AVANÇADA", "exact": False},
                {"tipo": "evaluate_text", "alvo": "PESQUISA AVANÇADA"},
                {"tipo": "locator", "alvo": "text=PESQUISA AVANÇADA"},
            ],
        )
        acoes.append({"acao": "abrir_pesquisa_avancada", **acao})
        await page.wait_for_timeout(2000)
        await salvar_etapa(page, etapas, "pesquisa_avancada_aberta", "Pesquisa avançada aberta.", {"acao": acao})

        acao = await preencher_campo_busca(page, TITULO_OFICIAL)
        acoes.append({"acao": "preencher_titulo_oficial", **acao})
        await page.wait_for_timeout(1000)
        await salvar_etapa(page, etapas, "titulo_preenchido", "Título oficial preenchido no campo de pesquisa.", {"acao": acao})

        for label in [
            "Resultado exato",
            "Pesquisa Ato-a-Ato",
            "Tudo",
            "Por data",
            "Personalizado",
        ]:
            acao = await tentar_check(page, f"Selecionar opção {label}", label)
            acoes.append({"acao": f"selecionar_{label}", **acao})
            await page.wait_for_timeout(600)
            await salvar_etapa(
                page,
                etapas,
                f"opcao_{normalizar_texto(label).replace(' ', '_')}",
                f"Opção selecionada: {label}",
                {"acao": acao},
            )

        acao_inicio = await preencher_data_por_label_ou_posicao(page, "Início", data_br(DATA_EXECUCAO))
        acoes.append({"acao": "preencher_data_inicio", **acao_inicio})
        await page.wait_for_timeout(500)

        acao_fim = await preencher_data_por_label_ou_posicao(page, "Fim", data_br(DATA_EXECUCAO))
        acoes.append({"acao": "preencher_data_fim", **acao_fim})
        await page.wait_for_timeout(1000)
        await salvar_etapa(
            page,
            etapas,
            "datas_preenchidas",
            "Datas Início e Fim preenchidas.",
            {"inicio": acao_inicio, "fim": acao_fim},
        )

        acao = await tentar_click(
            page,
            "Clicar Pesquisar",
            [
                {"tipo": "role_button", "alvo": re.compile("PESQUISAR", re.I)},
                {"tipo": "text", "alvo": "PESQUISAR", "exact": True},
                {"tipo": "evaluate_text", "alvo": "PESQUISAR"},
                {"tipo": "locator", "alvo": "button:has-text('PESQUISAR')"},
            ],
        )
        acoes.append({"acao": "clicar_pesquisar", **acao})

        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_timeout(6000)
        await salvar_etapa(page, etapas, "resultado_busca", "Resultado da busca carregado.", {"acao": acao})

        links_modernos = await coletar_links_modernos(page)

        print("=" * 80)
        print("LINKS MODERNOS ENCONTRADOS")
        print("=" * 80)
        for link in links_modernos[:30]:
            print(f"- {link.get('texto')} | {link.get('href')}")
        print("=" * 80)

        await browser.close()

    payload = {
        "data": DATA_EXECUCAO.isoformat(),
        "titulo_oficial": TITULO_OFICIAL,
        "url_inicial": URL_INICIAL,
        "url_direta_equivalente": query_url_direta(TITULO_OFICIAL, DATA_EXECUCAO),
        "headless": HEADLESS,
        "acoes": acoes,
        "links_modernos_encontrados": links_modernos,
        "total_links_modernos": len(links_modernos),
        "etapas": etapas,
    }

    ARQ_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = []
    linhas.append("=" * 80)
    linhas.append("MAPEAMENTO BUSCA AVANÇADA DOU")
    linhas.append("=" * 80)
    linhas.append(f"Data: {DATA_EXECUCAO.isoformat()}")
    linhas.append(f"Título oficial: {TITULO_OFICIAL}")
    linhas.append(f"URL inicial: {URL_INICIAL}")
    linhas.append(f"URL direta equivalente: {payload['url_direta_equivalente']}")
    linhas.append("")
    linhas.append("AÇÕES EXECUTADAS")
    linhas.append("-" * 80)

    for acao in acoes:
        linhas.append(json.dumps(acao, ensure_ascii=False, indent=2))

    linhas.append("")
    linhas.append("LINKS MODERNOS ENCONTRADOS")
    linhas.append("-" * 80)

    if links_modernos:
        for link in links_modernos:
            linhas.append(f"- {link.get('texto')} | {link.get('href')}")
    else:
        linhas.append("Nenhum link moderno /web/dou/-/ encontrado.")

    linhas.append("")
    linhas.append("ETAPAS / SCREENSHOTS")
    linhas.append("-" * 80)

    for etapa in etapas:
        linhas.append(f"{etapa['ordem']}. {etapa['nome']} | {etapa['url']} | screenshot={etapa['screenshot']}")

    ARQ_TXT.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 80)
    print("MAPEAMENTO FINALIZADO")
    print("=" * 80)
    print(f"Links modernos encontrados: {len(links_modernos)}")
    print(f"JSON: {ARQ_JSON}")
    print(f"TXT: {ARQ_TXT}")
    print(f"Screenshots: {SCREENSHOT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
