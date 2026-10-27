"""Monitor DOU v6. Pesquisa visual pública via Playwright; sem login, sem bypass."""
import json, re, threading, time, traceback, webbrowser, csv, io
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, urlencode
from playwright.sync_api import sync_playwright

BASE=Path(__file__).resolve().parent
PORT=8765
LOCK=threading.Lock()
BUSY=threading.Lock()
STATE={'estado':'pronto','mensagem':'Pronto para pesquisar.','resultados':[],'diagnostico':[],'url':'','paginacao':[],'progresso':0,'total_processos':0,'falhas':[],'auditoria':[],'inicio':'','fim':'','modo_navegador':'visivel'}

def publish(**values):
    with LOCK: STATE.update(values)
def log(message):
    with LOCK: STATE['diagnostico'].append(str(message)[:650])

def find_frame(page):
    for frame in page.frames:
        try:
            if frame.get_by_text('PESQUISA AVANÇADA', exact=False).count() or frame.get_by_text('Pesquisa Ato-a-Ato',exact=False).count():
                return frame
        except Exception: pass
    return page

def click_text(root, label):
    pat=re.compile(r'^\s*'+re.escape(label)+r'\s*$',re.I)
    for method in [lambda:root.get_by_label(label,exact=True),lambda:root.get_by_text(pat),lambda:root.get_by_text(label,exact=False)]:
        try:
            el=method().first
            if el.count(): el.click(timeout=4500); return True
        except Exception: pass
    return False

def radio(root,label):
    """Seleciona input radio por texto visível, mesmo quando o texto não é um <label>."""
    # Primeiro usar associação acessível do próprio formulário.
    try:
        target=root.get_by_role('radio',name=re.compile(r'^\s*'+re.escape(label)+r'\s*$',re.I))
        if target.count():
            target.first.check(timeout=2500,force=True)
            if target.first.is_checked():return True
    except Exception:pass
    # O formulário incorporado do DOU pode usar texto em <span> em vez de <label>.
    # Preferir clique no radio adjacente ao texto; conferir o estado depois.
    try:
        result=root.evaluate("""(label)=>{
          const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLocaleLowerCase('pt-BR');
          const name=norm(label);
          const radios=[...document.querySelectorAll('input[type=radio]')];
          for (const input of radios){
            const candidates=[input.closest('label'), input.parentElement,
              input.parentElement?.parentElement, input.nextElementSibling,
              input.previousElementSibling,
              input.id ? document.querySelector(`label[for="${CSS.escape(input.id)}"]`):null];
            if (!candidates.some(e=>e && norm(e.textContent)===name))continue;
            input.click();
            input.dispatchEvent(new Event('change',{bubbles:true}));
            return input.checked;
          }
          return false;
        }""",label)
        if result:return True
    except Exception:pass
    # Último recurso: clique no texto e verifique a seleção do radio no grupo.
    try:
        matches=root.get_by_text(re.compile(r'^\s*'+re.escape(label)+r'\s*$',re.I))
        for i in range(min(matches.count(),8)):
            try:
                el=matches.nth(i)
                el.click(timeout=1800,force=True)
                ok=el.evaluate("""e=>{const p=e.closest('label')||e.parentElement;
                    const r=p?.querySelector('input[type=radio]') ||
                    (e.htmlFor?document.getElementById(e.htmlFor):null);
                    return !!r?.checked;}""")
                if ok:return True
            except Exception:pass
    except Exception:pass
    return False

def find_search_input(root):
    candidates=root.locator('input:not([type=radio]):not([type=checkbox]):not([type=hidden]):not([type=date]):not([type=submit])')
    for i in range(min(candidates.count(),30)):
        el=candidates.nth(i)
        try:
            info=el.evaluate('(e)=>({r:e.getBoundingClientRect().width,placeholder:e.placeholder||"",type:e.type})')
            if info['r']>300 and info['type'] in ('text','search',''):
                return el
        except Exception:pass
    return None

def dates(root, start, end):
    """Campos reais identificados no mapeamento assistido de 22/10/2026."""
    for css, iso in (('#data-inicio', start), ('#data-fim',end)):
        el=root.locator(css)
        if not el.count():
            raise RuntimeError('Campo de data não encontrado: '+css)
        value=datetime.strptime(iso,'%Y-%m-%d').strftime('%d/%m/%Y')
        try:
            el.fill(value,timeout=6000)
            el.dispatch_event('input')
            el.dispatch_event('change')
            el.press('Tab',timeout=3000)
        except Exception as exc:
            raise RuntimeError('Não foi possível preencher '+css+': '+str(exc)[:180])
        log('Data preenchida: '+css+' = '+value)

def collect(page, search_term, mode):
    """Extrai os links de publicações da página atual em uma avaliação do DOM."""
    try:
        rows=page.evaluate("""() => Array.from(document.querySelectorAll('a[href*="/web/dou/-/"]')).map(a=>{
          const n=a.closest('h5')?.parentElement?.parentElement || a.parentElement?.parentElement || a.parentElement;
          return {titulo:(a.innerText||'').trim(),url:a.href,resumo:(n?.innerText||'').slice(0,1800)};
        }).filter(x=>x.titulo && x.url.startsWith('https://www.in.gov.br/'))""")
        return [dict(x,fontes=[mode]) for x in {x['url']:x for x in rows}.values()]
    except Exception as exc:
        log('Erro na captura: '+str(exc)[:170]);return []

def url_pesquisa(term,start,end,exact):
    # Para o modo exato, reproduz q="termo" visto no URL do teste de 22/10.
    # Para a busca ampliada, usa q=prefixo SEM aspas. Não pressupõe equivalência dos modos.
    q=('"'+term+'"') if exact else term
    args={'q':q,'s':'todos','exactDate':'personalizado','sortType':'0',
          'publishFrom':datetime.strptime(start,'%Y-%m-%d').strftime('%d-%m-%Y'),
          'publishTo':datetime.strptime(end,'%Y-%m-%d').strftime('%d-%m-%Y')}
    return 'https://www.in.gov.br/consulta/-/buscar/dou?'+urlencode(args)

def chave(txt):
    return ''.join(re.findall('[0-9a-z]+',txt.casefold()))

def validar(res,term):
    """Conferência de trechos: não afirma leitura do texto integral."""
    sample=res['resumo']
    if term.casefold() in sample.casefold():return 'Trecho: exato'
    if chave(term) and chave(term) in chave(sample):return 'Trecho: normalizado'
    return 'Conferir publicação'

def dados_paginacao(page):
    """Inspeciona botões numerados reais (#2btn, #3btn...), com fallback textual."""
    return page.evaluate("""() => {
      const v=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0};
      const out=[];
      for(const e of document.querySelectorAll('button,input[type=submit],a')){
        if(!v(e))continue;
        const id=e.id||'', text=(e.innerText||e.value||'').trim();
        const m=id.match(/^(\d+)btn$/);
        if(m)out.push({n:Number(m[1]),id:id});
        else if(/^\d+$/.test(text) && e.closest('[class*=pagin], [id*=pagin], nav'))
          out.push({n:Number(text),id:id});
      }
      return out.filter(x=>x.n>0&&x.n<100000);
    }""")

def total_reportado(page):
    try:
        body=page.locator('body').inner_text(timeout=6000)
        m=re.search(r'(\d[\d.]*)\s+resultados?\s+para',body,re.I)
        return int(m.group(1).replace('.','')) if m else None
    except Exception:return None

def paginas_resultado(page,term,modo,max_paginas=200):
    """Varre a paginação por botões #Nbtn, aguardando mudança real no conteúdo.
    Nunca presume cobertura concluída se o total não bater ou a navegação falhar.
    """
    saida={}; visitadas=0; problemas=[]; total=None; atual=1
    page.wait_for_timeout(1400)
    for tentativa in range(max_paginas):
        itens=collect(page,term,modo)
        for it in itens:saida[it['url']]=it
        visitadas+=1
        if total is None:total=total_reportado(page)
        log(f'{modo}: página {atual} capturada, {len(itens)} links nesta página, {len(saida)} distintos; total do portal: {total if total is not None else "indisponível"}.')
        if total is not None and len(saida)>=total:
            if len(saida)>total:problemas.append('Mais links capturados que o total declarado pelo portal; verificar extração.')
            break
        # O portal expõe botões #2btn, #3btn. Outros números podem surgir após avançar.
        try:numeros=dados_paginacao(page)
        except Exception as exc:
            problemas.append('Falha ao identificar botões de paginação: '+str(exc)[:150]);break
        prox_num=atual+1
        candidatos=[x for x in numeros if x['n']==prox_num]
        if not candidatos:
            # Forçar busca pelo ID mesmo quando a inspeção dos botões não o inclui.
            try:
                if not page.locator(f'[id="{prox_num}btn"]').count():
                    if total is not None and len(saida)<total:
                        problemas.append(f'Não encontrei botão da página {prox_num}; {len(saida)} de {total} resultados capturados.')
                    elif total is None:problemas.append('Não há total informado pelo portal para confirmar cobertura.')
                    break
            except Exception:break
        antes=tuple(sorted(x['url'] for x in itens))
        try:
            alvo=page.locator(f'[id="{prox_num}btn"]').first
            if not alvo.count():
                alvo=page.get_by_role('button',name=str(prox_num),exact=True).first
            if not alvo.count():alvo=page.get_by_role('link',name=str(prox_num),exact=True).first
            if not alvo.count():raise RuntimeError('botão não localizado')
            alvo.click(timeout=8000)
            mudou=False
            for _ in range(18):
                page.wait_for_timeout(450)
                novos=collect(page,term,modo)
                assinatura=tuple(sorted(x['url'] for x in novos))
                if assinatura and assinatura!=antes:
                    mudou=True;break
            if not mudou:
                problemas.append(f'Página {prox_num} não apresentou resultados diferentes após clique; interrompido para evitar repetição.')
                break
            atual=prox_num
        except Exception as exc:
            problemas.append(f'Falha ao acessar página {prox_num}: {str(exc)[:190]}');break
    else: problemas.append(f'Limite de segurança de {max_paginas} páginas atingido.')
    if total is not None and len(saida)!=total:
        problemas.append(f'Divergência: portal informa {total}, foram extraídos {len(saida)} links únicos.')
    for erro in problemas:log('PAGINAÇÃO INCOMPLETA — '+modo+': '+erro)
    completa=(total is not None and len(saida)==total and not problemas)
    log(f'{modo}: {visitadas} página(s) visitada(s); cobertura '+('CONFIRMADA por contagem.' if completa else 'NÃO CONFIRMADA.'))
    return list(saida.values()), {'modo':modo,'paginas_visitadas':visitadas,'total_portal':total,'capturados':len(saida),'completa':completa,'problemas':problemas}

def pesquisar_lote(params):
    browser=None
    processos=params['processos']; inicio=params['inicio']; fim=params['fim']; ampliada=params.get('ampliada',False); modo_navegador=params.get('modo_navegador','visivel')
    achados={}; falhas=[]; feitos=0; relatorios=[]; auditoria=[]
    try:
        with sync_playwright() as p:
            for channel in ('msedge','chrome',None):
                try:
                    browser=p.chromium.launch(headless=(modo_navegador=='oculto'), **({'channel':channel} if channel else {}));break
                except Exception as exc:log('Navegador '+str(channel)+': '+str(exc)[:140])
            if browser is None:raise RuntimeError('Edge/Chrome não disponível')
            context=browser.new_context(locale='pt-BR',viewport={'width':1380,'height':900})
            page=context.new_page()
            for dado in processos:
                numero = dado['processo']
                indice_falhas = len(falhas)
                indice_relatorios = len(relatorios)
                modalidades = [('Resultado exato', numero, True)]

                if ampliada:
                    prefixo = numero.split('/')[0]
                    modalidades.append(('Busca ampliada', prefixo, False))

                ultimo_erro = None
                relatorios_tentativa = []

                for tentativa in range(1, 4):
                    relatorios_tentativa = []
                    achados_tentativa = {}

                    try:
                        for modo, termo, exata in modalidades:
                            publish(
                                mensagem=(
                                    f'Pesquisando {feitos+1}/{len(processos)}: '
                                    f'{numero} - tentativa {tentativa}/3'
                                )
                            )
                            log(
                                f'Pesquisa {numero} / {modo} / '
                                f'tentativa {tentativa}/3'
                            )

                            resp = page.goto(
                                url_pesquisa(termo, inicio, fim, exata),
                                wait_until='domcontentloaded',
                                timeout=60000
                            )

                            if resp is None:
                                raise RuntimeError(
                                    'Navegacao sem resposta HTTP'
                                )

                            if resp.status >= 400:
                                raise RuntimeError(
                                    'HTTP ' + str(resp.status)
                                )

                            results, rel = paginas_resultado(
                                page, termo, modo, max_paginas=300
                            )
                            rel['processo'] = numero
                            relatorios_tentativa.append(rel)

                            if not rel.get('completa'):
                                raise RuntimeError(
                                    'Cobertura nao confirmada em '
                                    + modo + ': '
                                    + '; '.join(
                                        str(x)
                                        for x in rel.get('problemas', [])
                                    )
                                )

                            for x in results:
                                u = x['url']

                                if u not in achados_tentativa:
                                    achados_tentativa[u] = {
                                        **x,
                                        'processos': [],
                                        'fontes': []
                                    }

                                item = achados_tentativa[u]

                                if (
                                    numero not in item['processos']
                                    and (
                                        exata
                                        or validar(x, numero)
                                        != 'Conferir publicação'
                                    )
                                ):
                                    item['processos'].append(numero)

                                item['fontes'] = list(dict.fromkeys(
                                    item['fontes'] + [modo]
                                ))

                        # Confirmar todas as modalidades antes de
                        # incorporar os resultados ao lote.
                        relatorios.extend(relatorios_tentativa)

                        for u, item in achados_tentativa.items():
                            if u not in achados:
                                achados[u] = item
                            else:
                                achados[u]['processos'] = list(
                                    dict.fromkeys(
                                        achados[u]['processos']
                                        + item['processos']
                                    )
                                )
                                achados[u]['fontes'] = list(
                                    dict.fromkeys(
                                        achados[u]['fontes']
                                        + item['fontes']
                                    )
                                )

                        ultimo_erro = None
                        log(
                            f'Processo concluido: {numero} '
                            f'na tentativa {tentativa}/3'
                        )
                        break

                    except Exception as exc:
                        ultimo_erro = str(exc)[:300]
                        log(
                            f'FALHA {numero} tentativa '
                            f'{tentativa}/3: {ultimo_erro}'
                        )

                        if tentativa < 3:
                            try:
                                page.close()
                            except Exception:
                                pass

                            time.sleep(2 * tentativa)
                            page = context.new_page()

                if ultimo_erro is not None:
                    # Preservar somente o diagnostico da ultima
                    # tentativa, sem incorpora-lo como cobertura valida.
                    relatorios.extend(relatorios_tentativa)
                    falhas.append({
                        'processo': numero,
                        'erro': (
                            'Falhou apos 3 tentativas: '
                            + ultimo_erro
                        )
                    })
                    log(
                        'FALHA DEFINITIVA ' + numero
                        + ': ' + ultimo_erro
                    )

                feitos += 1
                rels=relatorios[indice_relatorios:]
                quantidade=sum(1 for x in achados.values() if numero in x['processos'])
                falhou=len(falhas)>indice_falhas or len(rels)!=len(modalidades) or not all(r.get('completa') for r in rels)
                auditoria.append({'processo':numero,'orgao':dado.get('orgao',''),'empresa':dado.get('empresa',''),'produto':dado.get('produto',''),
                    'inicio':inicio,'fim':fim,'modalidades':', '.join(m[0] for m in modalidades),
                    'publicacoes':quantidade,'paginas_visitadas':sum(r.get('paginas_visitadas',0) for r in rels),
                    'total_informado':sum(r.get('total_portal') or 0 for r in rels),
                    'situacao':('Cobertura não confirmada' if falhou else ('Publicações encontradas' if quantidade else 'Nenhuma ocorrência retornada')),
                    'observacoes':' | '.join(x.get('erro','') for x in falhas[indice_falhas:]),
                    'executado_em':datetime.now().isoformat(timespec='seconds')})
                publish(progresso=feitos,resultados=[x for x in achados.values() if x['processos']],falhas=list(falhas),paginacao=list(relatorios),auditoria=list(auditoria))
            result=[x for x in achados.values() if x['processos']]
            for x in result:x['classificacao']='Trecho a conferir; não houve leitura integral'
            completo=not falhas and len(relatorios)==len(processos)*(2 if ampliada else 1)
            publish(estado='concluido' if completo else 'parcial',mensagem=f'{feitos}/{len(processos)} processos pesquisados; {len(result)} publicações únicas. '+('Todas as consultas tiveram contagem conferida.' if completo else 'ATENÇÃO: existem consultas sem cobertura confirmada.'),resultados=result,falhas=falhas,paginacao=relatorios,auditoria=auditoria,progresso=feitos)
            browser.close();browser=None
    except Exception as exc:
        log('FALHA GERAL: '+str(exc)[:300]);publish(estado='erro',mensagem='Falha geral: '+str(exc)[:200],falhas=falhas)
    finally:
        try:
            if browser:browser.close()
        except Exception:pass
        BUSY.release()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(BASE),**kwargs)
    def reply(self,d,status=200):
        b=json.dumps(d,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/processos':
            return self.reply(json.loads((BASE/'processos.json').read_text(encoding='utf8')))
        if path=='/api/exportar_excel':
            try:
                from artifact_tool import Workbook, SpreadsheetFile
                with LOCK:
                    resultados=list(STATE['resultados']); auditoria=list(STATE['auditoria']); inicio=STATE.get('inicio',''); fim=STATE.get('fim','')
                if not auditoria:
                    return self.reply({'erro':'Execute uma pesquisa antes de baixar a auditoria.'},409)
                wb=Workbook.create(); a=wb.worksheets.add('Auditoria'); b=wb.worksheets.add('Publicações')
                h_a=['Processo','Órgão','Empresa','Produto','Data inicial','Data final','Tipos de pesquisa','Publicações','Páginas visitadas','Total declarado (soma das buscas)','Situação','Observações','Executado em']
                ra=[h_a]+[[str(x.get('processo','')),str(x.get('orgao','')),str(x.get('empresa','')),str(x.get('produto','')),
                    x.get('inicio',''),x.get('fim',''),x.get('modalidades',''),x.get('publicacoes',0),x.get('paginas_visitadas',0),
                    x.get('total_informado',0),x.get('situacao',''),x.get('observacoes',''),x.get('executado_em','')] for x in auditoria]
                a.get_range_by_indexes(0,0,len(ra),len(h_a)).values=ra
                h_b=['Processo(s)','Título','Link oficial','Resumo','Modalidade(s)','Classificação']
                rb=[h_b]+[[', '.join(x.get('processos',[])),x.get('titulo',''),x.get('url',''),x.get('resumo',''),', '.join(x.get('fontes',[])),x.get('classificacao','')] for x in resultados]
                b.get_range_by_indexes(0,0,len(rb),len(h_b)).values=rb
                for i,x in enumerate(resultados,2):
                    url=x.get('url','')
                    if url.startswith('https://www.in.gov.br/'):
                        # HYPERLINK with escaped literal; formula creates clickable hyperlink in Excel.
                        safe=url.replace('"','""')
                        b.get_range(f'C{i}').formulas=[[f'=HYPERLINK("{safe}","Abrir publicação no DOU")']]
                for sh,cols,n in ((a,'M',len(ra)),(b,'F',len(rb))):
                    sh.get_range(f'A1:{cols}1').format.fill='#143550'
                    sh.get_range(f'A1:{cols}1').format.font.color='#FFFFFF'
                    sh.get_range(f'A1:{cols}1').format.font.bold=True
                    sh.freeze_panes.freeze_rows(1)
                    sh.get_range(f'A1:{cols}{max(n,2)}').format.row_height=22
                for c,w in [('A',24),('B',24),('C',25),('D',25),('E',15),('F',15),('G',32),('H',15),('I',16),('J',26),('K',32),('L',38),('M',22)]:a.get_range(f'{c}:{c}').format.column_width=w
                for c,w in [('A',28),('B',56),('C',30),('D',75),('E',28),('F',35)]:b.get_range(f'{c}:{c}').format.column_width=w
                import tempfile,os
                with tempfile.NamedTemporaryFile(suffix='.xlsx',delete=False) as f: tmp=f.name
                try:
                    SpreadsheetFile.export_xlsx(wb).save(tmp)
                    corpo=Path(tmp).read_bytes()
                finally:
                    if Path(tmp).exists():Path(tmp).unlink()
                self.send_response(200);self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');self.send_header('Content-Disposition','attachment; filename=monitor_dou_auditoria.xlsx');self.send_header('Content-Length',str(len(corpo)));self.end_headers();self.wfile.write(corpo);return
            except Exception as exc:
                log('Falha ao gerar Excel: '+str(exc)[:300]);return self.reply({'erro':'Falha ao gerar Excel: '+str(exc)},500)
        if path=='/api/exportar':
            with LOCK: dados=list(STATE['resultados']); falhas=list(STATE['falhas'])
            buf=io.StringIO(); writer=csv.writer(buf,delimiter=';');writer.writerow(['processos','titulo','url','resumo','fontes'])
            for x in dados:writer.writerow([', '.join(x['processos']),x['titulo'],x['url'],x['resumo'],', '.join(x['fontes'])])
            corpo=('\ufeff'+buf.getvalue()).encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename=resultado_dou_20261022.csv');self.send_header('Content-Length',str(len(corpo)));self.end_headers();self.wfile.write(corpo);return
        if path=='/api/status':
            with LOCK:s=dict(STATE);s['diagnostico']=list(STATE['diagnostico']);s['resultados']=list(STATE['resultados'])
            return self.reply(s)
        if path in ('/','/index.html'):self.path='/index.html';return super().do_GET()
        self.send_error(404)
    def do_POST(self):
        if urlparse(self.path).path!='/api/pesquisar':return self.reply({'erro':'Não encontrado'},404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>20000:raise ValueError('Requisição muito grande')
            req=json.loads(self.rfile.read(length));inicio=str(req['inicio']);fim=str(req['fim'])
            a=datetime.strptime(inicio,'%Y-%m-%d');b=datetime.strptime(fim,'%Y-%m-%d')
            if a>b:raise ValueError('Data inicial depois da data final')
            catalogo=json.loads((BASE/'processos.json').read_text(encoding='utf8'))
            selecionados=req.get('processos')
            if not isinstance(selecionados,list) or not selecionados:raise ValueError('Selecione pelo menos um processo')
            mapa={d['processo']:d for d in catalogo}
            lista=[]
            for k in dict.fromkeys(selecionados):
                if not isinstance(k,str):raise ValueError('Número de processo inválido')
                k=k.strip()
                if not re.fullmatch(r'[0-9][0-9./-]{3,79}',k):raise ValueError('Formato de processo inválido: '+k[:80])
                lista.append(mapa.get(k,{'processo':k,'orgao':'','empresa':'','produto':'','linha':'manual'}))
            if not lista:raise ValueError('Nenhum processo válido selecionado')
            if len(lista)>500:raise ValueError('Limite de segurança: 500 processos por consulta')
            ampliada=req.get('ampliada') is True
            modo_navegador=req.get('modo_navegador','visivel')
            if modo_navegador not in ('visivel','oculto'):raise ValueError('Modo de navegador inválido')
        except Exception as exc:return self.reply({'erro':str(exc)},400)
        if not BUSY.acquire(False):return self.reply({'erro':'Existe pesquisa em andamento.'},409)
        publish(estado='pesquisando',mensagem='Abrindo o navegador...',resultados=[],diagnostico=[],paginacao=[],falhas=[],progresso=0,total_processos=len(lista),auditoria=[],inicio=inicio,fim=fim,modo_navegador=modo_navegador)
        threading.Thread(target=pesquisar_lote,args=({'processos':lista,'inicio':inicio,'fim':fim,'ampliada':ampliada,'modo_navegador':modo_navegador},),daemon=True).start()
        return self.reply({'ok':True})
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'Monitor DOU Emergencial em http://127.0.0.1:{PORT}',flush=True)
    threading.Thread(target=lambda:(time.sleep(1),webbrowser.open(f'http://127.0.0.1:{PORT}')),daemon=True).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
