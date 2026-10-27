# -*- coding: utf-8 -*-
"""Controle auditavel do monitoramento diario de processos por fonte (DEV 2026).

Infraestrutura isolada. Nao pesquisa fontes, nao sincroniza planilha e nao
promove processos na revisao historica. Somente recebe fatos COMPROVADOS dos
executores, registra status e preserva a trilha de tentativas.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[2]
PASTA_REGISTROS = (ROOT_DIR / 'backend' / 'data' / 'dou' / 'pesquisas'
                   / 'processos_2026' / 'controle_diario_por_fonte')
FONTES = ('DOU', 'ANVISA_DICOL_ATAS', 'ANVISA_DICOL_PAUTAS')
STATUS_PENDENTE = 'PENDENTE'
STATUS_PESQUISADO_COM_PUBLICACAO = 'PESQUISADO_COM_PUBLICACAO'
STATUS_PESQUISADO_SEM_PUBLICACAO = 'PESQUISADO_SEM_PUBLICACAO'
STATUS_FONTE_SEM_NOVIDADE = 'FONTE_VERIFICADA_SEM_NOVIDADE'
STATUS_FALHA = 'NAO_FOI_POSSIVEL_PESQUISAR'
STATUS_PARCIAL = 'COBERTURA_PARCIAL'
STATUS_VALIDOS = {
    STATUS_PENDENTE,
    STATUS_PESQUISADO_COM_PUBLICACAO,
    STATUS_PESQUISADO_SEM_PUBLICACAO,
    STATUS_FONTE_SEM_NOVIDADE,
    STATUS_FALHA,
    STATUS_PARCIAL,
}
STATUS_CONCLUIDOS = {
    STATUS_PESQUISADO_COM_PUBLICACAO,
    STATUS_PESQUISADO_SEM_PUBLICACAO,
    STATUS_FONTE_SEM_NOVIDADE,
}
ORIGENS_VALIDAS = {'INLABS', 'SITE_DOU', 'AMBOS', 'SITE_ANVISA', 'ARQUIVO_LOCAL', 'NAO_APLICAVEL'}


def _instante() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def _identidade(processo: str) -> str:
    return ''.join(c for c in str(processo or '') if c.isdigit())


def _validar_data(data: str) -> str:
    d = dt.date.fromisoformat(data)
    if d.year != 2026:
        raise ValueError('Esta versao cobre somente o ano 2026')
    return d.isoformat()


def _validar_processo(processo: str) -> str:
    valor = str(processo or '').strip()
    if len(_identidade(valor)) != 17:
        raise ValueError(f'Numero de processo invalido: {valor!r}')
    return valor


def caminho_dia(data: str, pasta: Path | None = None) -> Path:
    data = _validar_data(data)
    return (pasta if pasta is not None else PASTA_REGISTROS) / f'{data}.json'


def _ler(caminho: Path) -> dict[str, Any]:
    j = json.loads(caminho.read_text(encoding='utf-8-sig'))
    if not isinstance(j, dict) or j.get('versao_schema') != 1:
        raise ValueError('Registro diario invalido; nao sobrescrever')
    if not isinstance(j.get('processos'), dict):
        raise ValueError('Registro diario sem mapa de processos')
    return j


def _salvar_atomico(caminho: Path, valor: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # Temporario unico para nao colidir com gravacoes de outros componentes.
    fd, temporario = tempfile.mkstemp(
        prefix=caminho.name + '.', suffix='.tmp', dir=str(caminho.parent)
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(valor, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        # BLOQUEIO_TEMPORARIO_JSON_DEV
        import time
        for tentativa in range(1, 19):
            try:
                os.replace(temporario, caminho)
                if tentativa > 1:
                    print("[GRADE] Gravacao concluida apos", tentativa, "tentativas")
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or tentativa == 18:
                    raise
                time.sleep(min(0.1 * tentativa, 0.5))
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def _novo_registro() -> dict[str, Any]:
    return {
        'status': STATUS_PENDENTE,
        'publicacoes_encontradas': None,
        'origem': None,
        'evidencia': None,
        'erro': None,
        'atualizado_em': None,
        'tentativas': [],
    }


def criar_grade_diaria(data: str, processos: Iterable[str], *,
                        pasta: Path | None = None) -> dict[str, Any]:
    """Inicializa matriz processo x fonte como PENDENTE, sem concluir pesquisas.

    Reruns preservam status e eventos existentes. Processos retirados da
    planilha sao preservados para auditoria; nunca apagados automaticamente.
    """
    caminho = caminho_dia(data, pasta)
    if caminho.is_file():
        diario = _ler(caminho)
        if diario.get('data_pesquisa') != _validar_data(data):
            raise ValueError('Data do registro em disco diverge do nome')
    else:
        diario = {
            'versao_schema': 1,
            'data_pesquisa': _validar_data(data),
            'criado_em': _instante(),
            'atualizado_em': None,
            'fontes': list(FONTES),
            'processos': {},
        }
    alterado = not caminho.exists()
    for processo in processos:
        processo = _validar_processo(processo)
        ident = _identidade(processo)
        atual = diario['processos'].get(ident)
        if atual is None:
            diario['processos'][ident] = {
                'processo': processo,
                'fontes': {fonte: _novo_registro() for fonte in FONTES},
            }
            alterado = True
        else:
            if not isinstance(atual, dict) or not isinstance(atual.get('fontes'), dict):
                raise ValueError('Registro do processo em disco invalido')
            for fonte in FONTES:
                if fonte not in atual['fontes']:
                    atual['fontes'][fonte] = _novo_registro()
                    alterado = True
    if alterado:
        diario['atualizado_em'] = _instante()
        _salvar_atomico(caminho, diario)
    return diario


def registrar_resultado(*, data: str, processo: str, fonte: str,
                       status: str, origem: str | None = None,
                       evidencia: dict[str, Any] | None = None,
                       publicacoes_encontradas: int | None = None,
                       erro: str | None = None,
                       pasta: Path | None = None) -> dict[str, Any]:
    """Registra tentativa de uma fonte/proc.; sucesso exige prova explicita.

    Nao cria automaticamente processos: devem ser inicializados a partir da
    planilha validada. Estado concluido so muda se houve novos PDFs no dia;
    as tentativas anteriores ficam preservadas para auditoria.
    """
    if fonte not in FONTES:
        raise ValueError('Fonte invalida')
    if status not in STATUS_VALIDOS - {STATUS_PENDENTE}:
        raise ValueError('Status invalido para tentativa')
    ident = _identidade(_validar_processo(processo))
    caminho = caminho_dia(data, pasta)
    if not caminho.is_file():
        raise FileNotFoundError('Grade do dia nao iniciada com os processos da planilha')
    diario = _ler(caminho)
    if diario.get('data_pesquisa') != data:
        raise ValueError('Data divergente')
    reg = diario['processos'].get(ident)
    if not isinstance(reg, dict) or fonte not in reg.get('fontes', {}):
        raise KeyError('Processo nao consta da grade diaria validada')
    if origem is not None and origem not in ORIGENS_VALIDAS:
        raise ValueError('Origem invalida')
    if status in STATUS_CONCLUIDOS:
        if not isinstance(evidencia, dict) or not evidencia.get('referencia'):
            raise ValueError('Sucesso exige evidencia com referencia verificavel')
        if not origem or origem == 'NAO_APLICAVEL':
            raise ValueError('Sucesso exige origem real do documento ou verificacao')
        if status == STATUS_FONTE_SEM_NOVIDADE and publicacoes_encontradas not in (None, 0):
            raise ValueError('Fonte sem novidade nao pode conter publicacoes')
        if status != STATUS_FONTE_SEM_NOVIDADE and publicacoes_encontradas is None:
            raise ValueError('Pesquisa concluida exige contagem explicita de publicacoes')
        if status == STATUS_PESQUISADO_COM_PUBLICACAO and not (publicacoes_encontradas or 0) > 0:
            raise ValueError('Status com publicacao exige contagem positiva')
        if status == STATUS_PESQUISADO_SEM_PUBLICACAO and publicacoes_encontradas != 0:
            raise ValueError('Status sem publicacao exige contagem zero')
        if erro:
            raise ValueError('Nao registrar sucesso com erro aberto')
    else:
        if status == STATUS_FALHA and not erro:
            raise ValueError('Falha exige justificativa')
        if publicacoes_encontradas is not None and publicacoes_encontradas < 0:
            raise ValueError('Contagem negativa')
    if publicacoes_encontradas is not None and (
        not isinstance(publicacoes_encontradas, int) or isinstance(publicacoes_encontradas, bool)
    ):
        raise TypeError('Contagem deve ser inteiro')

    campo = reg['fontes'][fonte]
    if not isinstance(campo, dict) or not isinstance(campo.get('tentativas'), list):
        raise ValueError('Historico de tentativas invalido')
    evento = {
        'status': status,
        'publicacoes_encontradas': publicacoes_encontradas,
        'origem': origem,
        'evidencia': evidencia,
        'erro': erro,
    }
    anterior = {campo_chave: campo.get(campo_chave) for campo_chave in evento}
    if anterior == evento:
        return diario  # Repeticao idempotente, sem escrita/duplicata
    if campo.get('status') in STATUS_CONCLUIDOS:
        # Uma descoberta POSTERIOR no mesmo dia pode revelar PDFs novos.
        # Nesse caso o estado do dia precisa refletir a nova cobertura,
        # sem apagar a tentativa bem-sucedida anterior. So permitir a
        # substituicao se o novo conjunto de documentos EXPLICITAMENTE cresceu.
        prova_anterior = campo.get('evidencia') or {}
        prova_nova = evidencia or {}
        if not isinstance(prova_anterior, dict) or not isinstance(prova_nova, dict):
            raise RuntimeError('Evidencia de pesquisa anterior ou nova invalida')
        total_anterior = int(prova_anterior.get('documentos_esperados') or 0)
        total_novo = int(prova_nova.get('documentos_esperados') or 0)
        if total_novo <= total_anterior:
            raise RuntimeError('Pesquisa concluida: nao sobrescrever sem nova cobertura de PDFs')
    quando = _instante()
    campo['tentativas'].append({'registrado_em': quando, **evento})
    campo.update(evento)
    campo['atualizado_em'] = quando
    diario['atualizado_em'] = quando
    _salvar_atomico(caminho, diario)
    return diario


def resumo_diario(data: str, *, pasta: Path | None = None) -> dict[str, Any]:
    diario = _ler(caminho_dia(data, pasta))
    totais = {f: {} for f in FONTES}
    for item in diario['processos'].values():
        for fonte in FONTES:
            status = item['fontes'][fonte]['status']
            totais[fonte][status] = totais[fonte].get(status, 0) + 1
    return {
        'data': data,
        'total_processos': len(diario['processos']),
        'por_fonte': totais,
    }
