# -*- coding: utf-8 -*-
"""Comprova pesquisa individual do DOU na data da base local validada.

Esta rotina NAO acessa a internet, NAO promove historicos e NAO declara
resultados do catch-up como pesquisa do dia. Proveniencia: arquivo local;
a origem remota (INLABS/SITE_DOU) so pode ser afirmada quando auditada.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from backend.services.registro_pesquisa_diaria_fontes_service import (
    criar_grade_diaria,
    registrar_resultado,
    STATUS_PESQUISADO_COM_PUBLICACAO,
    STATUS_PESQUISADO_SEM_PUBLICACAO,
    STATUS_FONTE_SEM_NOVIDADE,
)


def _id(numero: Any) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isdigit())


def registrar_pesquisa_diaria_dou_comprovada(
    *,
    data: str,
    processos: Iterable[str],
    resultados_dia: list[dict[str, Any]],
    registros_base: list[dict[str, Any]],
    caminho_base: Path,
    payload_base: Any,
    pasta_registros: Path | None = None,
) -> dict[str, Any]:
    """Grava DOUs pesquisados sem inventar sucesso na falta da base.

    O caller precisa ter lido a base, executado a busca e validado a saída.
    A função confere a identidade, a presença e a integridade da base.
    """
    dia = dt.date.fromisoformat(data).isoformat()
    numeros = tuple(processos)
    ids = [_id(p) for p in numeros]
    if not numeros or any(len(v) != 17 for v in ids) or len(set(ids)) != len(ids):
        raise ValueError("Universo de processos vazio, invalido ou duplicado")
    if not caminho_base.is_file():
        raise FileNotFoundError("Base DOU ausente para comprovar pesquisa")
    raw = caminho_base.read_bytes()
    # A integridade e comprovada pelo digest do arquivo local. A origem
    # INLABS ou SITE_DOU nao e deduzida do nome do arquivo.
    hash_base = hashlib.sha256(raw).hexdigest()
    arquivo_base = json.loads(raw.decode('utf-8-sig'))
    if arquivo_base != payload_base:
        raise RuntimeError("Base DOU mudou desde a leitura usada na pesquisa")
    if not isinstance(registros_base, list) or not isinstance(resultados_dia, list):
        raise TypeError("Listas de entrada invalidas")
    if any(not isinstance(x, dict) for x in registros_base + resultados_dia):
        raise TypeError("Registros de DOU ou resultados invalidos")
    status_base = ""
    if isinstance(payload_base, dict):
        status_base = str(
            payload_base.get('status_busca') or payload_base.get('status') or ''
        ).upper()
    if status_base in {'ERRO','FALHA','PARCIAL','CONCLUIDO_COM_PENDENCIAS'}:
        raise RuntimeError("Base DOU sem cobertura valida")
    sem_publicacoes = (not registros_base and status_base in {
        'SEM_PUBLICACOES', 'SEM_PUBLICACOES_CONFIRMADO'
    })
    if not registros_base and not sem_publicacoes:
        raise RuntimeError("Sem registros nem confirmacao de ausencia de publicacoes")
    contagem_por_processo = Counter()
    for resultado in resultados_dia:
        identidade = _id(resultado.get('processo') or resultado.get('processo_normalizado'))
        if identidade not in ids:
            raise RuntimeError("Resultado contem processo fora do universo pesquisado")
        contagem_por_processo[identidade] += 1
    if sem_publicacoes and resultados_dia:
        raise RuntimeError("Publicacoes relatadas em base oficialmente vazia")

    criar_grade_diaria(dia, numeros, pasta=pasta_registros)
    status_gerais = Counter()
    for numero, ident in zip(numeros, ids):
        total = contagem_por_processo.get(ident, 0)
        if total:
            status = STATUS_PESQUISADO_COM_PUBLICACAO
        elif sem_publicacoes:
            status = STATUS_FONTE_SEM_NOVIDADE
        else:
            status = STATUS_PESQUISADO_SEM_PUBLICACAO
        evidencia = {
            'referencia': str(caminho_base),
            'sha256': hash_base,
            'data_base': dia,
            'status_base': status_base or 'REGISTROS_DISPONIVEIS',
            'documentos_esperados': len(registros_base),
            'observacao': (
                'Pesquisa individual concluida no acervo DOU local; '
                'canal de coleta remota nao inferido.'
            ),
        }
        registrar_resultado(
            data=dia, processo=numero, fonte='DOU', status=status,
            origem='ARQUIVO_LOCAL', evidencia=evidencia,
            publicacoes_encontradas=total, pasta=pasta_registros,
        )
        status_gerais[status] += 1
    return {
        'status': 'CONCILIADO', 'data': dia,
        'processos': len(numeros), 'resultados': len(resultados_dia),
        'status_por_processo': dict(status_gerais),
        'base': str(caminho_base), 'sha256_base': hash_base,
        'origem_registrada': 'ARQUIVO_LOCAL',
    }
