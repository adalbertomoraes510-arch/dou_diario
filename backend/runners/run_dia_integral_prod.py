# -*- coding: utf-8 -*-
"""Monitoramento diario na producao: DOU, DICOL, acervo, e-mail.

A DICOL consulta sempre o portal, preserva copias imutaveis por SHA-256
e pesquisa os processos. Resultados por fonte; revisao historica desabilitada.
O e-mail usa o HTML e assunto padrao do servico da producao (do PROD).
Data retroativa: a busca DICOL acontece AGORA; nao prova o catalogo passado.

Uso: python testar_dia_isolado_dou_dicol_v3_fresco_email_dev.py --data 2026-10-23 --preflight
     python testar_dia_isolado_dou_dicol_v3_fresco_email_dev.py --data 2026-10-23 --executar
"""
from __future__ import annotations
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import traceback
from collections import Counter
from html import escape as escapar_html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONTES = ('DOU', 'ANVISA_DICOL_ATAS', 'ANVISA_DICOL_PAUTAS')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def guardar_atomico(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.'+path.name+'.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=2, ensure_ascii=False, default=str)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def id_processo(p: str) -> str:
    return ''.join(c for c in str(p or '') if c.isdigit())


def validar_prod() -> None:
    if ROOT.name.casefold() != 'dou_diario_prod' or not ROOT.is_dir():
        raise RuntimeError('ABORTADO: pasta PROD nao encontrada. Ambiente PROD obrigatorio.')
    if not (ROOT/'backend/runners/run_orquestrador_dou_periodo.py').is_file():
        raise RuntimeError('ABORTADO: codigo DOU nao encontrado no PROD.')
    if not (ROOT/'backend/services/registro_pesquisa_diaria_fontes_service.py').is_file():
        raise RuntimeError('ABORTADO: modulo de diario V3 nao instalado no PROD.')
    sys.path.insert(0, str(ROOT))


def carteira_validada() -> tuple[str,...]:
    from backend.services.controle_monitoramento_processos_service import (
        carregar_processos_atuais, carregar_json_seguro, CAMINHO_CONTROLE, STATUS_INATIVO)
    atual = tuple(carregar_processos_atuais())
    if not atual or len({id_processo(p) for p in atual}) != len(atual):
        raise RuntimeError('Planilha vazia ou processos duplicados: interrompido.')
    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    regs = estado.get('processos')
    if not isinstance(regs, dict):
        raise RuntimeError('Controle de carteira invalido.')
    carteira = {id_processo(k) for k,v in regs.items() if isinstance(v, dict)
                and v.get('ativo',True) and v.get('status') != STATUS_INATIVO}
    if carteira != {id_processo(p) for p in atual}:
        raise RuntimeError('Planilha e carteira divergentes; sincronizacao historica NAO executada.')
    return atual


def resolucao(data: str):
    dia = dt.date.fromisoformat(data)
    if dia.year != 2026 or dia > dt.date.today():
        raise RuntimeError('Data invalida: exigir dia nao futuro do ano 2026.')
    if dia.weekday() >= 5:
        raise RuntimeError('Data informada e fim de semana. Escolha dia util para o teste.')
    return dia


def obter_registro(diario: dict, processo: str, fonte: str) -> dict:
    return diario['processos'][id_processo(processo)]['fontes'][fonte]


def resumo_grade(diario: dict) -> dict:
    return {fonte: dict(Counter(v['fontes'][fonte]['status'] for v in diario['processos'].values()))
            for fonte in FONTES}


def registrar_em_lote(reg, dia: str, processos: tuple, fonte: str, status: str,
                      origem=None, evidencia=None, resultados=None, erro=None, pasta=None):
    for p in processos:
        chave = id_processo(p)
        hits = [r for r in (resultados or []) if id_processo(r.get('processo') or r.get('processo_normalizado')) == chave]
        qtde = len(hits) if status in {reg.STATUS_PESQUISADO_COM_PUBLICACAO, reg.STATUS_PESQUISADO_SEM_PUBLICACAO} else (0 if status == reg.STATUS_FONTE_SEM_NOVIDADE else None)
        escolhido = (reg.STATUS_PESQUISADO_COM_PUBLICACAO if hits else reg.STATUS_PESQUISADO_SEM_PUBLICACAO) if status == 'SEGUNDO_RESULTADOS' else status
        if status == 'SEGUNDO_RESULTADOS':
            qtde = len(hits)
        anterior = obter_registro(json.loads(reg.caminho_dia(dia,pasta).read_text(encoding='utf-8-sig')), p, fonte)
        if anterior['status'] in reg.STATUS_CONCLUIDOS:
            comprovados=int((anterior.get('evidencia') or {}).get('documentos_esperados') or 0)
            atuais=int((evidencia or {}).get('documentos_esperados') or 0)
            if atuais <= comprovados:
                continue  # Mesma cobertura ja comprovada; nao sobrescrever.
        reg.registrar_resultado(data=dia, processo=p, fonte=fonte, status=escolhido,
                               origem=origem, evidencia=evidencia, erro=erro,
                               publicacoes_encontradas=qtde, pasta=pasta)


def carregar_base_validada(dia):
    from backend.runners.run_pesquisa_processos_incremental_dou_2026 import (
        caminho_base_dou, carregar_json, extrair_registros_base)
    path = caminho_base_dou(dia)
    if not path.is_file():
        return None
    try:
        payload = carregar_json(path)
        registros = extrair_registros_base(payload)
        if isinstance(payload, dict):
            indicador = str(payload.get('status_busca') or payload.get('status') or '').upper()
            if indicador in ('ERRO', 'PARCIAL', 'COBERTURA_INCOMPLETA', 'FALHA'):
                return None
            data_arquivo = str(payload.get('data_referencia') or payload.get('data_execucao') or payload.get('data') or '')[:10]
            if data_arquivo and data_arquivo != dia.isoformat():
                return None
        if not registros:
            flag = str(payload.get('status_busca') or payload.get('status') or '').upper() if isinstance(payload,dict) else ''
            if flag not in ('SEM_PUBLICACOES', 'SEM_PUBLICACOES_CONFIRMADO'):
                return None
        return path, registros, len(registros) == 0
    except Exception:
        return None


async def coletar_dou_por_inlabs(dia):
    """Usa o pipeline oficial de uma UNICA data e uma unica finalidade, SEM e-mail."""
    from backend.orquestradores.orquestrador_dou import executar_pipeline_dou_multifinalidade
    ret = await executar_pipeline_dou_multifinalidade(
        data_execucao=dia,
        finalidades_config=['dou_diario'],
        max_paginas=None,
        limite_publicacoes=None,
        headless=True,
        executar_limpeza=False,
        limpeza_modo_simulacao=True,
        forcar_reprocessamento_base=False,
        forcar_reprocessamento_finalidades=False,
        continuar_se_finalidade_erro=False,
    )
    dados = (ret.get('resultado') or {}).get('finalidades') or {}
    estado = str((dados.get('dou_diario') or {}).get('status') or '').upper()
    if estado != 'SUCESSO':
        raise RuntimeError('Pipeline INLABS sem SUCESSO na finalidade dou_diario: '+estado)
    return ret


def contingencia_v7(dia, processos, destino):
    """Motor V7 de processos; cobertura validada; resultados candidatos por processo."""
    from backend.operacao.services.adaptador_motor_v7 import pesquisar_processos
    resposta=pesquisar_processos(
        processos=[{'processo':p} for p in processos],
        data_inicial=dia,data_final=dia,modo_navegador='oculto')
    auditoria=resposta.get('auditoria') or []
    paginacao=resposta.get('paginacao') or []
    falhas=resposta.get('falhas') or []
    concluido=(str(resposta.get('estado') or '').lower()=='concluido'
          and len(auditoria)==len(processos) and len(paginacao)==len(processos)
          and not falhas and all(isinstance(p,dict) and p.get('completa') is True for p in paginacao))
    busca={id_processo(p):p for p in processos}
    normalizados=[]
    for item in resposta.get('resultados') or []:
        if not isinstance(item,dict): continue
        numeros=item.get('processos') or ([item.get('processo')] if item.get('processo') else [])
        if not isinstance(numeros,list): numeros=[numeros]
        for numero in numeros:
            ident=id_processo(numero)
            if ident not in busca:continue
            registro=dict(item)
            registro.update({'processo':busca[ident],
                'trecho':str(item.get('resumo') or item.get('trecho') or ''),
                'tipo_match':'CANDIDATO_CONTINGENCIA_V7'})
            normalizados.append(registro)
    comprovante=dict(resposta)
    comprovante['resultados_normalizados']=normalizados
    comprovante['cobertura_processos_comprovada']=concluido
    arquivo=destino/'evidencias'/'dou_v7_completo.json'
    if arquivo.exists():
        arquivo=destino/'evidencias'/('dou_v7_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    guardar_atomico(arquivo,comprovante)
    if not concluido:
        raise RuntimeError('V7 sem cobertura individual comprovada; prova: '+str(arquivo))
    return arquivo,normalizados

def executar_dou(dia, processos, pasta, reg):
    """Pesquisa da data; INLABS e palavras-chave, base local, V7 processos.

    Nunca implica que V7 cobre palavras-chave nao processuais.
    """
    data = dia.isoformat()
    diario = json.loads(reg.caminho_dia(data,pasta).read_text(encoding='utf-8-sig'))
    faltantes = tuple(p for p in processos if obter_registro(diario,p,'DOU')['status'] not in reg.STATUS_CONCLUIDOS)
    # Se ja houver prova completa em execucao desta data, nao repetir processamento.
    controle_pipeline = pasta.parent/'evidencias'/'dou_inlabs_palavras_chave.json'
    if not faltantes and controle_pipeline.is_file():
        estado_pipeline=json.loads(controle_pipeline.read_text(encoding='utf-8-sig'))
        if estado_pipeline.get('status')=='PESQUISADO':
            print('[DOU] Comprovantes anteriores preservados.'); return
    erros=[]
    # A busca de TODAS as demais palavras-chave precisa passar pelo pipeline normal.
    # A pesquisa dos processos da V7 nao cobre essas palavras.
    try:
        print('[DOU] Executando INLABS e regras das palavras-chave para',data)
        retorno = asyncio.run(coletar_dou_por_inlabs(dia))
        from backend.services import email_dou_diario_service as modelo
        caminho_modelo=modelo.montar_caminho_modelo_json(dia)
        caminho_txt=modelo.montar_caminho_relatorio_txt(dia)
        if not (caminho_modelo.is_file() and caminho_txt.is_file()):
            raise RuntimeError('Pipeline sem relatorio executivo das palavras-chave na data')
        publicacoes=modelo.carregar_publicacoes_relevantes(dia)
        guardar_atomico(controle_pipeline,{
            'data':data, 'status':'PESQUISADO', 'origem':'INLABS',
            'executado_em':dt.datetime.now().isoformat(timespec='seconds'),
            'modelo_json':str(caminho_modelo),'sha256_modelo':sha256(caminho_modelo),
            'relatorio_txt':str(caminho_txt),'sha256_relatorio':sha256(caminho_txt),
            'publicacoes_palavras_chave':publicacoes,
        })
        print('[DOU] Palavras-chave INLABS pesquisadas:',len(publicacoes))
    except Exception as exc:
        erros.append('PALAVRAS_CHAVE_INLABS: '+str(exc))
        if not controle_pipeline.is_file():
            guardar_atomico(controle_pipeline,{
                'data':data,'status':'NAO_FOI_POSSIVEL_PESQUISAR',
                'erro':str(exc)[:1800], 'executado_em':dt.datetime.now().isoformat(timespec='seconds')
            })
        print('[DOU] Palavras-chave NAO comprovadas pelo INLABS:',str(exc)[:200])
    if not faltantes:
        return
    base=carregar_base_validada(dia)
    if base is not None:
        path, registros, sem_publicacoes=base
        try:
            from backend.services.pesquisa_processos_dou_service import pesquisar_processos_nos_registros
            resultados=pesquisar_processos_nos_registros(registros=registros, processos=faltantes)
            prova=pasta.parent/'evidencias'/'dou_pesquisa_base_local.json'
            guardar_atomico(prova,{
                'data_referencia':data,'origem':'BASE_DOU_VALIDA',
                'base':str(path),'sha256_base':sha256(path),
                'processos_pesquisados':list(faltantes),'resultados':resultados,
                'executado_em':dt.datetime.now().isoformat(timespec='seconds')})
            ev={'referencia':str(prova),'sha256':sha256(prova),
                'processos_pesquisados':list(faltantes)}
            registrar_em_lote(reg,data,faltantes,'DOU',
                reg.STATUS_FONTE_SEM_NOVIDADE if sem_publicacoes else 'SEGUNDO_RESULTADOS',
                origem='ARQUIVO_LOCAL',evidencia=ev,resultados=resultados,pasta=pasta)
            print('[DOU] Processos pesquisados na base da data:',len(faltantes))
            return
        except Exception as exc:
            erros.append('BASE_DOU: '+str(exc))
    try:
        arquivo, resultados=contingencia_v7(dia,faltantes,pasta.parent)
        ev={'referencia':str(arquivo),'sha256':sha256(arquivo),
            'processos_pesquisados':list(faltantes)}
        registrar_em_lote(reg,data,faltantes,'DOU','SEGUNDO_RESULTADOS',
            origem='SITE_DOU',evidencia=ev,resultados=resultados,pasta=pasta)
        print('[DOU] Contingencia V7 concluiu processos:',len(faltantes))
    except Exception as exc:
        erros.append('CONTINGENCIA_V7: '+str(exc))
        registrar_em_lote(reg,data,faltantes,'DOU',reg.STATUS_FALHA,
            origem='SITE_DOU',erro=' | '.join(erros)[:1800],pasta=pasta)
        print('[DOU] SEM pesquisa comprovada:',str(exc)[:250])

def descobrir_dicol_sem_historico(anual):
    """Consulta diretamente os dois catalogos oficiais; nenhum controle local."""
    documentos, erros = [], []
    sessao = anual.criar_sessao_http_anvisa()
    try:
        for fonte, url in anual.ANVISA_FONTES.items():
            try:
                encontrados = anual.descobrir_pdfs_fonte_anvisa(
                    sessao=sessao, nome_fonte=fonte, url_raiz=url)
                if not encontrados:
                    raise RuntimeError('Catalogo retornou zero PDFs; cobertura nao comprovada.')
                documentos.extend(encontrados)
            except Exception as exc:
                erros.append({'fonte':fonte,'etapa':'CATALOGO','erro':str(exc)[:1000]})
    finally:
        try: sessao.close()
        except Exception: pass
    urls = [str(d.get('url_pdf') or '') for d in documentos]
    if any(not u for u in urls) or len(set(urls)) != len(urls):
        raise RuntimeError('Catalogo DICOL contem URLs ausentes ou duplicadas.')
    return sorted(documentos,key=lambda d:(d.get('fonte',''),d.get('titulo',''))),erros


def _inventario_acervo_dicol(acervo, fonte):
    """Todas as versoes imutaveis da fonte, inclusive fora do catalogo atual."""
    subpasta = 'atas' if fonte == 'ANVISA_DICOL_ATAS' else 'pautas'
    inventario = {}
    for pdf in sorted((acervo / subpasta).glob('*.pdf')):
        digest = pdf.stem.lower()
        if not re.fullmatch(r'[a-f0-9]{64}', digest) or sha256(pdf) != digest:
            raise RuntimeError('PDF do acervo com nome/hash divergente: ' + str(pdf))
        meta = acervo / 'metadados' / fonte / (digest + '.json')
        if not meta.is_file():
            raise RuntimeError('PDF sem metadado: ' + str(pdf))
        registro = json.loads(meta.read_text(encoding='utf-8-sig'))
        if registro.get('sha256') != digest or registro.get('fonte') != fonte:
            raise RuntimeError('Metadados inconsistentes: ' + str(meta))
        inventario[digest] = (pdf, registro)
    return inventario


def executar_dicol(dia, processos, pasta, reg):
    """Consulta portal diariamente E pesquisa todas as versoes acumuladas.

    Falha do catalogo NUNCA vira sucesso por causa do acervo. Pesquisa retroativa
    tambem nao equivale a consulta do catalogo na data passada.
    """
    import importlib
    import shutil
    anual = importlib.import_module('backend.runners.run_pesquisa_processos_dou_2026')
    data = dia.isoformat()
    retroativo = dia != dt.date.today()
    acervo = ROOT / 'backend/data/dou/pesquisas/processos_2026/acervo_dicol_permanente'
    try:
        documentos, erros_descoberta = descobrir_dicol_sem_historico(anual)
    except Exception as exc:
        documentos = []
        erros_descoberta = [{'fonte': f, 'etapa': 'CATALOGO', 'erro': str(exc)} for f in FONTES[1:]]
    consultado_em = dt.datetime.now().isoformat(timespec='seconds')
    arq_cat = pasta.parent / 'evidencias' / 'dicol_catalogo_consultado.json'
    guardar_atomico(arq_cat, {
        'data_referencia': data, 'consultado_em': consultado_em,
        'documentos': [{k: d.get(k) for k in ('fonte','titulo','url_pdf','url_item')} for d in documentos],
        'erros': erros_descoberta,
        'ressalva_retroativa': retroativo,
    })
    for fonte in FONTES[1:]:
        lista = [dict(d) for d in documentos if d.get('fonte') == fonte]
        erros_catalogo = [e for e in erros_descoberta if not isinstance(e,dict) or e.get('fonte') in (None,'',fonte)]
        documento_dia = json.loads(reg.caminho_dia(data,pasta).read_text(encoding='utf-8-sig'))
        faltantes = tuple(p for p in processos if obter_registro(documento_dia,p,fonte)['status'] not in reg.STATUS_CONCLUIDOS)
        if not faltantes:
            print('[DICOL]',fonte,'ja concluida nesta data; conservada.')
            continue
        erros_pdf = []
        diagnosticos = []
        resultados_novos = []
        resultados_acumulados = []
        try:
            inventario_anterior = _inventario_acervo_dicol(acervo, fonte)
        except Exception as exc:
            inventario_anterior = {}
            erros_pdf.append({'etapa':'INTEGRIDADE_ACERVO','erro':str(exc)[:600]})
        novos_digests = set()
        # A verificacao do portal e obrigatoria, mas nao impede a leitura do acervo.
        campos_originais = (anual.PROCESSOS_PESQUISA,anual.ANVISA_PDFS_DIR,
                            anual.ANVISA_OCR_DIR,anual.ANVISA_DEBUG_DIR)
        with tempfile.TemporaryDirectory(prefix='dicol_diario_dev_') as tmp:
            temporario = Path(tmp)
            try:
                anual.PROCESSOS_PESQUISA = tuple(faltantes)
                anual.ANVISA_PDFS_DIR = temporario/'pdfs'
                anual.ANVISA_OCR_DIR = temporario/'ocr'
                anual.ANVISA_DEBUG_DIR = temporario/'debug'
                for diretorio in (anual.ANVISA_PDFS_DIR,anual.ANVISA_OCR_DIR,anual.ANVISA_DEBUG_DIR):
                    diretorio.mkdir(parents=True,exist_ok=True)
                if not erros_catalogo and lista:
                    sessao = None
                    try:
                        sessao = anual.criar_sessao_http_anvisa()
                        for doc in lista:
                            try:
                                baixado = Path(anual.baixar_pdf_anvisa(sessao,doc,forcar_download=True))
                                digest = sha256(baixado)
                                destino = acervo/('atas' if fonte == 'ANVISA_DICOL_ATAS' else 'pautas')/(digest+'.pdf')
                                if destino.is_file():
                                    if sha256(destino) != digest:
                                        raise RuntimeError('PDF arquivado alterado: '+str(destino))
                                else:
                                    destino.parent.mkdir(parents=True,exist_ok=True)
                                    with destino.open('xb') as saida, baixado.open('rb') as entrada:
                                        shutil.copyfileobj(entrada,saida)
                                        saida.flush();os.fsync(saida.fileno())
                                    if sha256(destino) != digest:
                                        raise RuntimeError('Falha de integridade da copia')
                                    novos_digests.add(digest)
                                meta = acervo/'metadados'/fonte/(digest+'.json')
                                if not meta.exists():
                                    guardar_atomico(meta,{'fonte':fonte,'sha256':digest,
                                        'titulo_primeira_captura':doc.get('titulo'),
                                        'url_primeira_captura':doc.get('url_pdf'),
                                        'url_item':doc.get('url_item'),
                                        'capturado_em':consultado_em,'arquivo':str(destino)})
                            except Exception as exc:
                                erros_pdf.append({'etapa':'DOWNLOAD','titulo':doc.get('titulo'),'erro':str(exc)[:600]})
                    except Exception as exc:
                        erros_pdf.append({'etapa':'CONEXAO','erro':str(exc)[:600]})
                    finally:
                        if sessao is not None:
                            sessao.close()
                # Inclui baseline + versoes que sairam do catalogo + novas versoes.
                try:
                    inventario = _inventario_acervo_dicol(acervo,fonte)
                except Exception as exc:
                    inventario = {}
                    erros_pdf.append({'etapa':'INTEGRIDADE_ACERVO_FINAL','erro':str(exc)[:600]})
                for digest,(pdf,meta) in inventario.items():
                    doc = {'fonte':fonte,'titulo':meta.get('titulo_primeira_captura'),
                           'url_pdf':meta.get('url_primeira_captura'),
                           'url_item':meta.get('url_item')}
                    try:
                        hits, leitura = anual.pesquisar_processos_pdf_anvisa(pdf,doc)
                        if int(leitura.get('erros_paginas') or 0) or leitura.get('status_leitura') not in ('TEXTO_EXTRAIDO','TEXTO_EXTRAIDO_OCR'):
                            raise RuntimeError('PDF sem leitura integral: '+str(leitura.get('status_leitura')))
                        limpos = [{k:v for k,v in hit.items() if k not in
                            ('arquivo_pdf','arquivo_pdf_original','arquivo_pdf_ocr','arquivo_log_ocr')} for hit in hits]
                        resultados_acumulados.extend(limpos)
                        if digest in novos_digests:
                            resultados_novos.extend(limpos)
                        diagnosticos.append({'sha256_pdf':digest,'arquivo_permanente':str(pdf),
                            'status':'PESQUISADO','ocorrencias':len(limpos),
                            'novo_documento':digest in novos_digests})
                    except Exception as exc:
                        erros_pdf.append({'etapa':'PESQUISA_ACERVO','sha256_pdf':digest,'erro':str(exc)[:600]})
            finally:
                (anual.PROCESSOS_PESQUISA,anual.ANVISA_PDFS_DIR,
                 anual.ANVISA_OCR_DIR,anual.ANVISA_DEBUG_DIR) = campos_originais
        prova = pasta.parent/'evidencias'/('dicol_'+fonte.lower()+'_arquivo.json')
        catalogo_ok = not erros_catalogo and bool(lista) and not any(e.get('etapa') in ('DOWNLOAD','CONEXAO') for e in erros_pdf)
        acervo_ok = bool(diagnosticos) and not erros_pdf
        guardar_atomico(prova,{'data':data,'consultado_em':consultado_em,
            'catalogo':str(arq_cat),'sha256_catalogo':sha256(arq_cat),
            'consulta_diaria_ok':catalogo_ok,'pesquisa_acervo_ok':acervo_ok,
            'documentos_catalogo':len(lista),'documentos_acervo':len(diagnosticos),
            'processos_pesquisados':list(faltantes),'diagnosticos':diagnosticos,
            'resultados':resultados_novos,'resultados_acumulados':resultados_acumulados,
            'falhas_catalogo':erros_catalogo,'falhas_acervo':erros_pdf,
            'ressalva_retroativa':retroativo})
        ev = {'referencia':str(prova),'sha256':sha256(prova),
              'documentos_esperados':len(diagnosticos),'documentos_pesquisados':len(diagnosticos),
              'consulta_diaria_ok':catalogo_ok,'pesquisa_acervo_ok':acervo_ok}
        if not catalogo_ok or not acervo_ok:
            status=reg.STATUS_FALHA
            erro='Consulta diaria: '+('OK' if catalogo_ok else 'FALHA')+'; acervo: '+('OK' if acervo_ok else 'FALHA')
        elif retroativo:
            status=reg.STATUS_PARCIAL
            erro='Catalogo consultado hoje nao comprova a composicao do catalogo em '+data
        else:
            status='SEGUNDO_RESULTADOS';erro=None
        registrar_em_lote(reg,data,faltantes,fonte,status,origem='SITE_ANVISA',
                          evidencia=ev,resultados=resultados_novos,erro=erro,pasta=pasta)
        print('[DICOL]',fonte,'portal=',catalogo_ok,'acervo=',acervo_ok,
              'versoes=',len(diagnosticos),'novidades=',len(resultados_novos),'status=',status)

def imprimir_resumo(reg,pasta,data):
    j = json.loads(reg.caminho_dia(data,pasta).read_text(encoding='utf-8-sig'))
    print('\n========== RELATORIO POR PROCESSO/FONTE =========')
    print('DATA REFERENCIA:', data)
    print('EXECUTADO EM:',dt.datetime.now().isoformat(timespec='seconds'))
    print('TOTAL PROCESSOS:',len(j['processos']))
    for fonte,counts in resumo_grade(j).items():
        print(' ',fonte)
        for status,n in sorted(counts.items()): print('  ',status,n)
    print('CONTROLE:',reg.caminho_dia(data,pasta))
    print('OBS: DICOL arquiva versoes por SHA256. Data retroativa nao prova catalogo antigo.')
    return resumo_grade(j)


# ------------------------------------------------------------
# E-MAIL OPERACIONAL PROD (habilitacao obrigatoria)
# ------------------------------------------------------------
def configuracao_email_prod():
    """Destinatarios do PROD; envio requer habilitacao operacional explicita."""
    if ROOT.name.casefold() != 'dou_diario_prod':
        raise RuntimeError('Ambiente de producao invalido')
    try:
        from dotenv import load_dotenv
        for configuracao in (ROOT/'.env', ROOT/'backend'/'.env'):
            if configuracao.is_file():
                load_dotenv(dotenv_path=configuracao, override=False)
    except ImportError:
        pass
    if os.getenv('DOU_PROD_HABILITAR_EMAIL_DIARIO','').strip().upper() != 'SIM':
        return None
    if os.getenv('EMAIL_MODO_SIMULACAO','true').strip().lower() not in ('false','0','nao','não'):
        return None
    valores = [v.strip() for v in re.split(r'[,;]',os.getenv('EMAIL_DESTINATARIOS','')) if v.strip()]
    if not valores or any(not re.fullmatch(r'[^\s,;@]+@[^\s,;@]+\.[^\s,;@]+',v) for v in valores):
        return None
    return list(dict.fromkeys(valores))


def preparar_relatorio_email(dia, pasta, reg):
    """Inclui SEMPRE os 36 processos e suas tres fontes. Nao infere completude."""
    documento = json.loads(reg.caminho_dia(dia, pasta).read_text(encoding='utf-8-sig'))
    resumo = resumo_grade(documento)
    completo = all(
        estado in reg.STATUS_CONCLUIDOS
        for estados in resumo.values() for estado in estados
    ) and _palavras_chave_comprovadas(pasta)[0]
    linhas = []
    campos_assinatura = []
    for numero, info in sorted(documento['processos'].items()):
        processo = info.get('processo') or numero
        for fonte in FONTES:
            registro = info['fontes'][fonte]
            estado = str(registro.get('status') or reg.STATUS_PENDENTE)
            origem = str(registro.get('origem') or '-')
            n = registro.get('publicacoes_encontradas')
            erro = str(registro.get('erro') or '')
            evidencia = registro.get('evidencia') or {}
            local = str(evidencia.get('referencia') or '') if isinstance(evidencia,dict) else ''
            linhas.append((processo,fonte,estado,origem,n,erro,local))
            campos_assinatura.append([numero,fonte,estado,origem,n,
                                      str(evidencia.get('sha256') or '') if isinstance(evidencia,dict) else ''])
    return resumo, completo, linhas, campos_assinatura


def _linhas_publicacoes_provas(linhas,pasta):
    """Le publicacoes somente de provas locais da propria execucao."""
    arquivos={Path(r[6]) for r in linhas if r[6] and r[6]!='-'}
    saida=[];vistos=set()
    for arquivo in arquivos:
        try:
            if not arquivo.resolve().is_relative_to(pasta.parent.resolve()): continue
            if not arquivo.is_file():continue
            payload=json.loads(arquivo.read_text(encoding='utf-8-sig'))
            if isinstance(payload.get('resultados_normalizados') or payload.get('resultados'),list):
                for hit in (payload.get('resultados_normalizados') or payload.get('resultados')):
                    if not isinstance(hit,dict):continue
                    # Somente matches efetivos, V7 permanece candidato / conferir.
                    processo=str(hit.get('processo') or hit.get('processo_normalizado') or '')
                    if not processo: continue
                    titulo=str(hit.get('titulo') or hit.get('titulo_publicacao') or hit.get('ementa') or 'Publicação')
                    url=str(hit.get('url_item') or hit.get('url_pdf') or hit.get('url') or '')
                    trecho=str(hit.get('trecho') or hit.get('resumo') or hit.get('texto') or '')[:1300]
                    origem='DICOL' if 'dicol_' in arquivo.name else ('Contingência V7 — conferir' if 'dou_v7' in arquivo.name else 'DOU')
                    chave=(id_processo(processo),url,titulo,trecho[:140],origem)
                    if chave in vistos:continue
                    vistos.add(chave)
                    saida.append({'titulo':titulo,'orgao':'ANVISA/DICOL' if origem=='DICOL' else 'DOU',
                        'url':url,'termos':[],'trecho_relevante':trecho,
                        'fonte_monitoramento':origem,
                        'registro_original':{'processos_monitorados_detectados':[processo]},
                        'processos_detectados':[processo]})
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
            continue
    return saida


def _palavras_chave_comprovadas(pasta):
    arquivo=pasta.parent/'evidencias'/'dou_inlabs_palavras_chave.json'
    if not arquivo.is_file():return (False,[], 'INLABS sem comprovante das palavras-chave')
    dados=json.loads(arquivo.read_text(encoding='utf-8-sig'))
    if dados.get('status')!='PESQUISADO':
        return (False,[],str(dados.get('erro') or 'INLABS nao concluiu as palavras-chave'))
    lista=dados.get('publicacoes_palavras_chave') or []
    if not isinstance(lista,list):raise RuntimeError('Relatorio palavras-chave invalido')
    return (True,lista,'')



def montar_mensagem_email(dia, resumo, completo, linhas, pasta):
    """Resumo executivo no email, com detalhamento preservado no TXT."""
    from backend.services import email_dou_diario_service as modelo

    data = dt.date.fromisoformat(dia)
    comprovado, palavras, erro_palavras = _palavras_chave_comprovadas(pasta)
    processuais = _linhas_publicacoes_provas(linhas, pasta)
    publicacoes = processuais + palavras if comprovado else processuais

    concluidos = {
        'PESQUISADO_COM_PUBLICACAO',
        'PESQUISADO_SEM_PUBLICACAO',
        'FONTE_VERIFICADA_SEM_NOVIDADE'
    }

    por_fonte = {}
    for proc, fonte, estado, origem, n, erro, ref in linhas:
        por_fonte.setdefault(fonte, []).append((estado, n))

    fontes_esperadas = (
        'DOU',
        'ANVISA_DICOL_ATAS',
        'ANVISA_DICOL_PAUTAS'
    )

    processos_ok = (
        all(por_fonte.get(f) for f in fontes_esperadas)
        and all(
            estado in concluidos
            for f in fontes_esperadas
            for estado, n in por_fonte[f]
        )
    )

    com_publicacoes = any(
        estado == 'PESQUISADO_COM_PUBLICACAO'
        for f in fontes_esperadas
        for estado, n in por_fonte.get(f, [])
    )

    if processos_ok:
        if com_publicacoes:
            situacao_processos = (
                "Pesquisados no DOU e na ANVISA/DICOL, "
                "com publicacoes encontradas. Consulte as tabelas."
            )
        else:
            situacao_processos = (
                "Pesquisados no DOU e na ANVISA/DICOL, "
                "sem publicacoes encontradas."
            )
    else:
        situacao_processos = (
            "Pesquisa incompleta no DOU e/ou ANVISA/DICOL. "
            "Nao e possivel confirmar ausencia de publicacoes."
        )

    if comprovado:
        if palavras:
            situacao_palavras = (
                "Pesquisadas no INLABS, com publicacoes encontradas."
            )
        else:
            situacao_palavras = (
                "Pesquisadas no INLABS, sem publicacoes encontradas."
            )
    else:
        motivo = str(erro_palavras or "").strip()
        if "404" in motivo:
            situacao_palavras = (
                "Nao pesquisadas devido a indisponibilidade "
                "de acesso ao INLABS (HTTP 404)."
            )
        elif motivo:
            situacao_palavras = (
                "Nao pesquisadas devido a falha no INLABS: "
                + motivo[:160]
            )
        else:
            situacao_palavras = (
                "Nao pesquisadas. Acesso ao INLABS nao confirmado."
            )

    integral = bool(completo and processos_ok and comprovado)
    situacao_geral = (
        "Cobertura integral."
        if integral
        else "Cobertura parcial. Existem etapas nao concluidas."
    )

    def legivel(valor):
        return (
            valor.replace("publicacoes", "publica\u00e7\u00f5es")
                 .replace("publicacao", "publica\u00e7\u00e3o")
                 .replace("Nao", "N\u00e3o")
                 .replace("Nao e", "N\u00e3o \u00e9")
                 .replace("e possivel", "\u00e9 poss\u00edvel")
                 .replace("indisponibilidade", "indisponibilidade")
                 .replace("Nao", "N\u00e3o")
        )

    situacao_processos = legivel(situacao_processos)
    situacao_palavras = legivel(situacao_palavras)
    situacao_geral = legivel(situacao_geral).replace("Situacao", "Situa\u00e7\u00e3o").replace("nao", "n\u00e3o").replace("concluidas", "conclu\u00eddas"); situacao_palavras = situacao_palavras.replace("devido a indisponibilidade", "devido \u00e0 indisponibilidade")

    resumo_texto = [
        "Status do monitoramento - " + data.strftime("%d/%m/%Y"),
        "",
        "Processos: " + situacao_processos,
        "Palavras-chave: " + situacao_palavras,
    ]

    texto = list(resumo_texto)
    texto.extend([
        "",
        "DETALHAMENTO TECNICO - ANEXO",
        "Total de processos: " + str(len({x[0] for x in linhas})),
        "Cobertura: " + ("INTEGRAL" if integral else "PARCIAL"),
        ""
    ])

    for fonte, estados in resumo.items():
        texto.append(
            f"{fonte}: "
            + ", ".join(
                f"{chave}={valor}"
                for chave, valor in sorted(estados.items())
            )
        )

    texto.extend(["", "Detalhes por processo:"])
    for proc, fonte, estado, origem, n, erro, ref in linhas:
        texto.append(
            f"{proc} | {fonte} | {estado} | "
            f"origem={origem} | encontrados={n} | {erro[:240]}"
        )

    texto.extend(["", "Publicacoes apresentadas no email:"])
    for item in publicacoes:
        texto.append(
            f"{item.get('titulo')} | {item.get('url')} | "
            f"{item.get('fonte_monitoramento')}"
        )

    html = modelo.montar_corpo_email_dou_diario(
        data_execucao=data,
        resumo={},
        publicacoes=publicacoes
    )

    marcador = (
        '<strong>Status do monitoramento</strong><br><br>'
    )

    if html.count(marcador) != 1:
        raise RuntimeError(
            "Marcador do status do email nao encontrado"
        )

    status_html = (
        '<strong>Status do monitoramento - '
        + data.strftime("%d/%m/%Y")
        + '</strong><br><br>'
        + '<strong>Processos:</strong> '
        + escapar_html(situacao_processos)
        + '<br><br>'
        + '<strong>Palavras-chave:</strong> '
        + escapar_html(situacao_palavras)

    )

    html = html.replace(marcador, status_html, 1)

    assunto = modelo.montar_assunto_email(
        data_execucao=data,
        quantidade_publicacoes=len(publicacoes)
    )

    return assunto, '\n'.join(texto) + '\n', html

def enviar_relatorio_operacional_dev(dia, pasta, reg):
    """Envia e guarda prova; uma mensagem por versao substantiva dos resultados."""
    if ROOT.name.casefold() != 'dou_diario_prod':
        raise RuntimeError('Bloqueado: envio fora da producao.')
    email = configuracao_email_prod()
    if not email:
        print('[EMAIL] BLOQUEADO: envio PROD ainda nao habilitado.')
        return {'status':'BLOQUEADO_CONFIGURACAO_EMAIL_PROD'}
    resumo, completo, linhas, assinaturas = preparar_relatorio_email(dia, pasta, reg)
    classificacao, texto, html = montar_mensagem_email(dia, resumo, completo, linhas, pasta)
    assinatura_bytes = json.dumps(
        {'data':dia,'destinatarios':sorted(e.casefold() for e in email),'versao':6,'grade':assinaturas,'conteudo_email':hashlib.sha256((texto+html).encode('utf-8')).hexdigest()},
        ensure_ascii=False, sort_keys=True, separators=(',',':')).encode('utf-8')
    identificador = hashlib.sha256(assinatura_bytes).hexdigest()
    pasta_saida = pasta.parent/'email_operacional'
    caminho_controle = pasta_saida/f'envio_{identificador}.json'
    anexo = pasta_saida/f'relatorio_{identificador}.txt'
    if caminho_controle.exists():
        estado = json.loads(caminho_controle.read_text(encoding='utf-8-sig'))
        if estado.get('identificador') != identificador:
            raise RuntimeError('Controle de e-mail nao confere com identificador; nao sobrescrever')
        if estado.get('status') == 'ENVIADO':
            print('[EMAIL] JA ENVIADO; nenhum envio duplicado:',identificador[:12])
            return {'status':'ENVIADO','reutilizado':True,'comprovante':str(caminho_controle)}
        if estado.get('status') == 'ENVIO_INICIADO':
            print('[EMAIL] ENVIO INDETERMINADO: conferir destino antes de qualquer reenvio.')
            return {'status':'ENVIO_INDETERMINADO','comprovante':str(caminho_controle)}
    pasta_saida.mkdir(parents=True, exist_ok=True)
    # O anexo se refere exatamente aos dados utilizados no hash.
    anexo.write_text(texto, encoding='utf-8')
    registro = {'identificador':identificador,'data':dia,'destinatarios':email,
                'status':'ENVIO_INICIADO','iniciado_em':dt.datetime.now().isoformat(timespec='seconds'),
                'assunto':classificacao,'anexo':str(anexo),'sha256_anexo':sha256(anexo)}
    guardar_atomico(caminho_controle,registro)
    try:
        from backend.services.email_service import enviar_email
        resultado = enviar_email(
            assunto=classificacao,
            corpo_html=html, corpo_texto=texto, anexo=anexo,
            destinatarios=email, modo_simulacao=False)
        retorno = str((resultado or {}).get('status') or '').upper()
        if retorno != 'ENVIADO':
            registro.update({'status':'FALHA_ENVIO','retorno_servico':retorno,
                             'finalizado_em':dt.datetime.now().isoformat(timespec='seconds')})
            guardar_atomico(caminho_controle,registro)
            print('[EMAIL] NAO CONFIRMADO:',retorno)
            return {'status':'FALHA_ENVIO','retorno':retorno,'comprovante':str(caminho_controle)}
        registro.update({'status':'ENVIADO',
                         'confirmado_em':dt.datetime.now().isoformat(timespec='seconds')})
        guardar_atomico(caminho_controle,registro)
        print('[EMAIL] ENVIADO; comprovante:',caminho_controle)
        return {'status':'ENVIADO','comprovante':str(caminho_controle)}
    except Exception as exc:
        # Em excecao de transporte nao sabemos se servidor SMTP aceitou a mensagem.
        # Nao tentar automaticamente outra vez para evitar dupla entrega.
        registro.update({'status':'ENVIO_INDETERMINADO','erro':str(exc)[:600],
                         'registrado_em':dt.datetime.now().isoformat(timespec='seconds')})
        guardar_atomico(caminho_controle,registro)
        print('[EMAIL] ENVIO INDETERMINADO:',str(exc)[:300])
        return {'status':'ENVIO_INDETERMINADO','comprovante':str(caminho_controle)}


from contextlib import contextmanager

@contextmanager
def bloquear_execucao_concorrente():
    """Evita duas execucoes simultaneas pelo terminal e/ou frontend."""
    alvo=ROOT/'backend/data/dou/pesquisas/processos_2026/monitoramento_diario_operacional/.execucao.lock'
    alvo.parent.mkdir(parents=True,exist_ok=True)
    with alvo.open('a+b') as arquivo:
        arquivo.seek(0,2)
        if arquivo.tell()==0:
            arquivo.write(b'0');arquivo.flush();os.fsync(arquivo.fileno())
        arquivo.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(arquivo.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as erro:
            raise RuntimeError('Outra execucao diaria PROD ja esta em andamento. Nao iniciar em paralelo.') from erro
        try: yield
        finally:
            arquivo.seek(0)
            if os.name=='nt':
                msvcrt.locking(arquivo.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(arquivo.fileno(),fcntl.LOCK_UN)

def main(argv=None):
    parser = argparse.ArgumentParser(description='Monitoramento diario - DOU e DICOL - PROD')
    parser.add_argument('--data',default='2026-10-23',help='AAAA-MM-DD')
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument('--preflight',action='store_true',help='Diagnostico SEM escritas nem internet')
    modo.add_argument('--executar',action='store_true',help='Executa a data isolada; pode consultar fontes')
    args = parser.parse_args(argv)
    validar_prod()
    dia = resolucao(args.data)
    processos = carteira_validada()  # so leitura, nunca sincroniza historico
    destino = ROOT/'backend/data/dou/pesquisas/processos_2026/monitoramento_diario_operacional'/dia.isoformat()
    grade = destino/'grade'
    from backend.services import registro_pesquisa_diaria_fontes_service as reg
    print('='*72)
    print('MONITORAMENTO DIARIO DOU + DICOL - PROD')
    print('DATA:',dia.isoformat(),'PROCESSOS:',len(processos))
    print('REVISAO HISTORICA: DESABILITADA NESTE TESTE')
    print('ENVIO DE E-MAIL: condicionado a habilitacao explicita no PROD', 'LIMPEZA: NAO')
    print('RAIZ:',ROOT)
    print('='*72)
    if args.preflight:
        print('EMAIL: nenhum envio no preflight')
        print('BASE LOCAL DOU VALIDA:',bool(carregar_base_validada(dia)))
        print('DICOL: consulta portal atual; preserva todas versoes PDF por SHA256; sem revisar historico')
        print('CONTROLE TESTE EXISTENTE:',reg.caminho_dia(dia.isoformat(),grade).is_file())
        print('EMAIL PROD HABILITADO:', 'SIM' if configuracao_email_prod() else 'NAO')
        print('PRE-FLIGHT: SOMENTE LEITURA, SEM INTERNET, SEM ALTERACOES')
        return 0
    if not configuracao_email_prod():
        raise RuntimeError('ENVIO BLOQUEADO: habilitar DOU_PROD_HABILITAR_EMAIL_DIARIO=SIM e validar destinatarios/simulacao no PROD')
    with bloquear_execucao_concorrente():
        reg.criar_grade_diaria(dia.isoformat(),processos,pasta=grade)
        for rotina, execucao in (('DOU', executar_dou),('DICOL', executar_dicol)):
            try:
                execucao(dia,processos,grade,reg)
            except Exception as erro_execucao:
                print('[',rotina,'] FALHA NA ROTINA:',str(erro_execucao)[:450])
                fontes_afetadas = ('DOU',) if rotina == 'DOU' else FONTES[1:]
                for fonte in fontes_afetadas:
                    estado = json.loads(reg.caminho_dia(dia.isoformat(),grade).read_text(encoding='utf-8-sig'))
                    incompletos = tuple(p for p in processos if
                        obter_registro(estado,p,fonte)['status'] not in reg.STATUS_CONCLUIDOS)
                    if incompletos:
                        registrar_em_lote(reg,dia.isoformat(),incompletos,fonte,reg.STATUS_FALHA,
                            origem=('INLABS' if fonte=='DOU' else 'SITE_ANVISA'),
                            erro=f'Falha inesperada {rotina}: {str(erro_execucao)[:1100]}',pasta=grade)
        stats = imprimir_resumo(reg,grade,dia.isoformat())
        _, cobertura_integral, _, _ = preparar_relatorio_email(dia.isoformat(),grade,reg)
        palavras_ok, _, erro_palavras = _palavras_chave_comprovadas(grade)
        saida = destino/'resumo_execucao.json'
        guardar_atomico(saida,{
            'status':'EXECUTADO_PROD', 'data_referencia':dia.isoformat(),
            'executado_em':dt.datetime.now().isoformat(timespec='seconds'),
            'processos':len(processos),'fontes':stats,
            'cobertura_geral':'INTEGRAL' if cobertura_integral else 'PARCIAL',
            'palavras_chave_inlabs':{
                'status':'PESQUISADO' if palavras_ok else 'NAO_FOI_POSSIVEL_PESQUISAR',
                'erro':None if palavras_ok else erro_palavras
            },
            'observacoes':['DICOL consulta portal e mantem copias imutaveis em acervo permanente.', 'DICOL retroativa nao comprova catalogo antigo.',
                'Sem revisao historica, sem promover status e sem processamento de periodo.',
                'DOU pesquisa processos por base valida ou V7, demais palavras-chave somente via INLABS.']})
        print('RESUMO:',saida)
        email_resultado = enviar_relatorio_operacional_dev(dia.isoformat(),grade,reg)
        print('STATUS_EMAIL:',email_resultado.get('status'))
        guardar_atomico(saida, {**json.loads(saida.read_text(encoding='utf-8-sig')), 'email':email_resultado})
        if email_resultado.get('status') != 'ENVIADO':
            return 3
        return 0 if preparar_relatorio_email(dia.isoformat(),grade,reg)[1] else 2

if __name__=='__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('INTERROMPIDO: status ja gravados preservados; executar de novo para retomar.',file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print('FALHA DE PRECONDICAO OU INTEGRIDADE:',e,file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
