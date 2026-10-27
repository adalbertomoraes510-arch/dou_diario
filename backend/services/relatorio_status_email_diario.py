# -*- coding: utf-8 -*-
"""Resumo visual do monitoramento diario: apenas apresentação, sem envios."""
import html
import json

from backend.services import registro_pesquisa_diaria_fontes_service as reg
from backend.services.match_service import carregar_palavras_chave

COR_VERDE = '#18794e'
COR_VERMELHA = '#b42318'
COR_CINZA = '#667085'


def _estilo(texto, cor):
    return '<strong style="color:%s;">%s</strong>' % (cor, html.escape(str(texto)))


def montar_quadro_status(dia, pasta, comprovado, modalidade,
                         carteira_validada, id_processo, evidencia_processo_valida):
    """Retorna (HTML do quadro, mensagem sem processos, mensagem sem palavras-chave).

    Contagens processuais exigem status final e validacao da evidencia de cada fonte.
    Pesquisa de palavras-chave: comprovante global nao fornece contagem individual.
    """
    palavras, _, _ = carregar_palavras_chave('dou_diario')
    cadastradas = len({str(item.get('normalizado') or '').strip()
                       for item in palavras if item.get('normalizado')})
    if cadastradas < 1:
        raise RuntimeError('Nenhuma palavra-chave cadastrada na finalidade dou_diario')

    processos = {id_processo(p) for p in carteira_validada()}
    if not processos:
        raise RuntimeError('Carteira de processos vazia')
    total = len(processos)

    controle = json.loads(reg.caminho_dia(dia, pasta).read_text(encoding='utf-8-sig'))
    registros = controle.get('processos') or {}
    if controle.get('data_pesquisa') != dia or not isinstance(registros, dict):
        raise RuntimeError('Controle diario sem data ou processos validos')

    def validos(fonte):
        saida = set()
        for numero in processos:
            registro = ((registros.get(numero) or {}).get('fontes') or {}).get(fonte)
            if (isinstance(registro, dict)
                and registro.get('status') in reg.STATUS_CONCLUIDOS
                and evidencia_processo_valida(dia, pasta, numero, fonte, registro)):
                saida.add(numero)
        return saida

    dou = validos('DOU')
    atas = validos('ANVISA_DICOL_ATAS')
    pautas = validos('ANVISA_DICOL_PAUTAS')
    dicol = atas & pautas
    portal = {numero for numero in dou if
              ((registros.get(numero) or {}).get('fontes') or {}).get('DOU', {}).get('origem') == 'SITE_DOU'}

    def qtd(valor):
        return _estilo('%s de %s pesquisados' % (valor, total),
                       COR_VERDE if valor == total else COR_VERMELHA)

    if comprovado:
        # O comprovante confirma o lote, mas nao traz contagem individual por termo.
        situacao_inlabs = _estilo('Disponível', COR_VERDE)
        situacao_palavras = _estilo('Lote pesquisado (quantidade individual não comprovada)', COR_VERDE)
    else:
        indisponivel = modalidade == 'CONTINGENCIA_V7'
        situacao_inlabs = _estilo('Indisponível' if indisponivel else 'Não confirmado', COR_VERMELHA)
        situacao_palavras = _estilo(
            '0 de %s pesquisadas - INLABS indisponível' % cadastradas
            if indisponivel else 'Pesquisa não comprovada', COR_VERMELHA)

    if portal:
        situacao_dou = qtd(len(portal))
    elif len(dou) == total:
        situacao_dou = _estilo('Não utilizado', COR_CINZA)
    else:
        situacao_dou = _estilo('Não comprovado', COR_VERMELHA)

    cabecalhos = ('Monitoramento', 'Cadastrados',
                  'INLABS', 'DOU - Portal Oficial', 'ANVISA/DICOL')
    def celula(valor, cabecalho=False):
        tag = 'th' if cabecalho else 'td'
        fundo = 'background-color:#eef2f6;' if cabecalho else ''
        return '<%s style="border:1px solid #cfd5dc;padding:8px;vertical-align:top;%s">%s</%s>' % (
            tag, fundo, valor, tag)

    cabecalho = '<tr>' + ''.join(celula(html.escape(x), True) for x in cabecalhos) + '</tr>'
    linha_proc = '<tr>' + ''.join(celula(x) for x in (
        '<strong>Processos</strong>', str(total),
        situacao_inlabs, situacao_dou, qtd(len(dicol))
    )) + '</tr>'
    linha_pal = '<tr>' + ''.join(celula(x) for x in (
        '<strong>Palavras-chave</strong>', str(cadastradas),
        situacao_palavras,
        _estilo('Não se aplica', COR_CINZA),
        _estilo('Não se aplica', COR_CINZA)
    )) + '</tr>'
    quadro = ('<strong>RESUMO E STATUS DO MONITORAMENTO</strong>'
              '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
              'width:100%;font-size:12px;margin-top:12px;">'
              + cabecalho + linha_proc + linha_pal + '</table>')

    if len(dou & dicol) == total:
        vazio_proc = _estilo('Nenhuma publicação identificada nos processos pesquisados.', COR_VERDE)
    else:
        vazio_proc = _estilo('Pesquisa incompleta: não é possível confirmar ausência de publicações.', COR_VERMELHA)
    if comprovado:
        vazio_pal = _estilo('Nenhuma publicação identificada nas palavras-chave pesquisadas.', COR_VERDE)
    elif modalidade == 'CONTINGENCIA_V7':
        vazio_pal = _estilo('Pesquisa não realizada - INLABS indisponível.', COR_VERMELHA)
    else:
        vazio_pal = _estilo('Pesquisa não comprovada no INLABS.', COR_VERMELHA)

    return quadro, vazio_proc, vazio_pal
