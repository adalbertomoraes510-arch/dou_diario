# -*- coding: utf-8 -*-
"""Concilia provas de pesquisa de PDFs DICOL com o diario processo/fonte.

* Nao acessa sites, nao faz download, nao extrai texto nem altera PDFs.
* Nunca considera status de documento suficiente: exige journal por processo.
* A conclusao e exclusiva da pesquisa INCREMENTAL; nao libera historicos.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from backend.services.controle_documentos_anvisa_service import carregar_json
from backend.services.registro_pesquisa_diaria_fontes_service import (
    criar_grade_diaria, registrar_resultado, PASTA_REGISTROS,
    STATUS_PESQUISADO_COM_PUBLICACAO, STATUS_PESQUISADO_SEM_PUBLICACAO,
    STATUS_FONTE_SEM_NOVIDADE, STATUS_FALHA, STATUS_PARCIAL,
)

FONTES = ("ANVISA_DICOL_ATAS", "ANVISA_DICOL_PAUTAS")
ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROLE = (ROOT_DIR / "backend/data/dou/pesquisas/processos_2026"
            / "controle_documentos_anvisa_2026.json")
DESCOBERTA = (ROOT_DIR / "backend/data/dou/pesquisas/processos_2026"
              / "anvisa_incremental/logs/ultima_descoberta_documentos_anvisa_2026.json")


def identidade(processo: str) -> str:
    return "".join(c for c in str(processo or "") if c.isdigit())


def _validar_journal(chave: str, registro: dict[str, Any]) -> tuple[dict | None, str | None]:
    if registro.get("status") != "PROCESSADO_INCREMENTAL":
        return None, f"Documento nao concluido: {registro.get('status')}"
    local = str(registro.get("resultado_journal") or "")
    if not local or not Path(local).is_file():
        return None, "Journal de documento nao localizado"
    try:
        j = carregar_json(Path(local))
        if j.get("chave_documento") != chave:
            raise ValueError("Chave do journal divergente")
        hash_pdf = str(j.get("hash_conteudo") or "")
        if len(hash_pdf) != 64 or any(c not in "0123456789abcdef" for c in hash_pdf.lower()):
            raise ValueError("SHA de PDF ausente ou invalido")
        if hash_pdf != registro.get("hash_conteudo"):
            raise ValueError("SHA do PDF diverge entre controle e journal")
        if not isinstance(j.get("processos_pesquisados"), list):
            raise ValueError("Lista de processos pesquisados ausente")
        if not isinstance(j.get("resultados"), list):
            raise ValueError("Lista de resultados ausente")
        if len(j["resultados"]) != registro.get("total_resultados_incremental"):
            raise ValueError("Quantidade de resultados diverge do controle")
        diag = j.get("diagnostico_pdf")
        if not isinstance(diag, dict) or diag.get("status_leitura") not in {
            "TEXTO_EXTRAIDO", "TEXTO_EXTRAIDO_OCR"
        }:
            raise ValueError("Leitura validada de PDF nao comprovada")
        if str(diag.get("ocr_status") or "").upper() == "ERRO":
            raise ValueError("Erro OCR no journal")
        total = int(diag.get("total_paginas") or 0)
        com_texto = int(diag.get("paginas_com_texto") or 0)
        if total <= 0 or com_texto < total or int(diag.get("erros_paginas") or 0):
            raise ValueError("Cobertura PDF incompleta")
        return j, None
    except Exception as exc:
        return None, str(exc)



def _arquivar_comprovante_descoberta(caminho: Path, *, dia: str,
                                   pasta: Path | None) -> tuple[Path, str]:
    """Copia o log remoto para arquivo imutavel enderecado por SHA-256.

    A descoberta oficial guarda apenas a ultima execucao; sem esta copia,
    a referencia no diario deixa de apontar para a evidencia original.
    """
    conteudo = caminho.read_bytes()
    hash_log = hashlib.sha256(conteudo).hexdigest()
    raiz = pasta if pasta is not None else PASTA_REGISTROS
    destino = raiz / "evidencias_descoberta" / dia / (hash_log + ".json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        if hashlib.sha256(destino.read_bytes()).hexdigest() != hash_log:
            raise RuntimeError("Comprovante de descoberta existente foi alterado")
        return destino, hash_log
    fd, nome = tempfile.mkstemp(prefix=".descoberta_", suffix=".tmp", dir=str(destino.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        if destino.exists():
            raise RuntimeError("Comprovante de descoberta apareceu durante gravacao")
        os.replace(nome, destino)
        if hashlib.sha256(destino.read_bytes()).hexdigest() != hash_log:
            destino.unlink(missing_ok=True)
            raise RuntimeError("SHA do comprovante arquivado falhou")
    finally:
        if os.path.exists(nome):
            os.unlink(nome)
    return destino, hash_log

def conciliar_dicol_diaria(*, data: str, processos: tuple[str, ...],
                           controle: dict[str, Any] | None = None,
                           caminho_descoberta: Path | None = None,
                           pasta_registros: Path | None = None) -> dict[str, Any]:
    """Registra SOMENTE evidencia verificavel do dia, separada por fonte.

    Reconcilia PDFs descobertos hoje, PDFs processados hoje e backlog pendente;
    nao reabre automaticamente os 22 documentos do baseline e nao altera
    controles de documentos/processos ou seus journals anteriores.
    """
    dia = dt.date.fromisoformat(data).isoformat()
    if len({identidade(p) for p in processos}) != len(processos):
        raise RuntimeError("Processos duplicados na planilha")
    criar_grade_diaria(dia, processos, pasta=pasta_registros)
    resposta: dict[str, Any] = {
        "data": dia, "processos": len(processos), "fontes": {},
        "observacao": "Registro incremental, SEM promover revisao historica",
    }
    caminho = caminho_descoberta or DESCOBERTA
    if not caminho.is_file():
        resposta["status"] = "SEM_DESCOBERTA_NA_DATA"
        return resposta
    log = carregar_json(caminho)
    if not str(log.get("gerado_em") or "").startswith(dia):
        resposta["status"] = "SEM_DESCOBERTA_NA_DATA"
        return resposta
    if controle is None:
        controle = carregar_json(CONTROLE)
    registros = controle.get("documentos")
    if not isinstance(registros, dict):
        raise ValueError("Controle de documentos invalido")
    erros_log = log.get("erros") or []
    if not isinstance(erros_log, list):
        raise ValueError("Lista de erros de descoberta invalida")
    status_descoberta = str(log.get("status") or "")
    if status_descoberta not in {"SUCESSO", "CONCLUIDO_COM_PENDENCIAS"}:
        resposta["status"] = "DESCOBERTA_NAO_VALIDADA"
        return resposta
    if not int(log.get("documentos_remotos") or 0):
        resposta["status"] = "DESCOBERTA_SEM_CATALOGO_VALIDO"
        return resposta

    comprovante, sha_comprovante = _arquivar_comprovante_descoberta(
        caminho, dia=dia, pasta=pasta_registros
    )
    resposta["comprovante_descoberta"] = str(comprovante)
    resposta["sha256_descoberta"] = sha_comprovante
    falhas_gerais = [e for e in erros_log if not isinstance(e, dict) or e.get("fonte") not in FONTES]
    for fonte in FONTES:
        falhas_fonte = [e for e in erros_log if isinstance(e, dict) and e.get("fonte") == fonte]
        falhas_fonte.extend(falhas_gerais)
        candidatos: list[tuple[str, dict[str, Any]]] = []
        for chave, item in registros.items():
            if not isinstance(item, dict) or item.get("fonte") != fonte or item.get("baseline"):
                continue
            data_primeira = str(item.get("primeira_identificacao_em") or "")[:10]
            data_exec = str(item.get("processado_em") or "")[:10]
            if data_primeira == dia or data_exec == dia or item.get("status") == "NOVO_PENDENTE":
                candidatos.append((str(chave), item))
        candidatos.sort(key=lambda x: x[0])
        journals = {chave: _validar_journal(chave, reg) for chave, reg in candidatos}
        contagem = Counter()
        for processo in processos:
            if falhas_fonte:
                estado = STATUS_FALHA
                kwargs = {
                    "erro": "; ".join(str(e.get("erro") or "Erro na descoberta") if isinstance(e, dict) else str(e) for e in falhas_fonte),
                    "origem": "SITE_ANVISA",
                    "evidencia": {"referencia": str(comprovante), "sha256": sha_comprovante,
                                  "etapa": "descoberta"},
                }
            elif not candidatos:
                estado = STATUS_FONTE_SEM_NOVIDADE
                kwargs = {
                    "origem": "SITE_ANVISA",
                    "evidencia": {"referencia": str(comprovante), "sha256": sha_comprovante,
                                  "documentos_novos": 0, "fonte": fonte},
                    "publicacoes_encontradas": 0,
                }
            else:
                sem_cobertura = []
                cobertos = []
                total_ocorrencias = 0
                for chave, reg in candidatos:
                    j, motivo = journals[chave]
                    if motivo:
                        sem_cobertura.append({"chave": chave, "motivo": motivo})
                        continue
                    consultados = {identidade(p) for p in j["processos_pesquisados"]}
                    if identidade(processo) not in consultados:
                        sem_cobertura.append({"chave": chave, "motivo": "Processo ausente do journal"})
                        continue
                    cobertos.append(chave)
                    total_ocorrencias += sum(
                        identidade(r.get("processo")) == identidade(processo)
                        for r in j["resultados"] if isinstance(r, dict)
                    )
                evidencia = {
                    "referencia": str(comprovante),
                    "sha256": sha_comprovante,
                    "fonte": fonte,
                    "documentos_esperados": len(candidatos),
                    "documentos_pesquisados": cobertos,
                    "documentos_sem_cobertura": sem_cobertura,
                }
                if sem_cobertura:
                    estado = STATUS_PARCIAL
                    kwargs = {"origem": "ARQUIVO_LOCAL", "evidencia": evidencia,
                              "publicacoes_encontradas": total_ocorrencias,
                              "erro": f"Sem cobertura em {len(sem_cobertura)}/{len(candidatos)} PDFs"}
                else:
                    estado = (STATUS_PESQUISADO_COM_PUBLICACAO if total_ocorrencias
                              else STATUS_PESQUISADO_SEM_PUBLICACAO)
                    kwargs = {"origem": "ARQUIVO_LOCAL", "evidencia": evidencia,
                              "publicacoes_encontradas": total_ocorrencias}
            registrar_resultado(data=dia, processo=processo, fonte=fonte,
                                status=estado, pasta=pasta_registros, **kwargs)
            contagem[estado] += 1
        resposta["fontes"][fonte] = dict(contagem)
    resposta["status"] = "CONCILIADO"
    return resposta
