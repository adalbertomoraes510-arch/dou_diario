# -*- coding: utf-8 -*-
"""Historico operacional DEV. Leitura exclusiva de evidencias locais."""

from pathlib import Path
from collections import Counter
import datetime as dt
import json
import hashlib
import re

DEV = Path(__file__).resolve().parents[2]
BASE = (
    DEV / "backend" / "data" / "dou" / "pesquisas"
    / "processos_2026" / "teste_dia_isolado_fresco_v3"
)

FONTES = {
    "DOU": "DOU - Processos",
    "ANVISA_DICOL_ATAS": "ANVISA/DICOL - Atas",
    "ANVISA_DICOL_PAUTAS": "ANVISA/DICOL - Pautas",
}

def ler_json(caminho):
    if not caminho.is_file():
        return None
    try:
        with caminho.open("r", encoding="utf-8-sig") as arq:
            valor = json.load(arq)
        return valor if isinstance(valor, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None

def consolidar_fonte(processos, codigo, descricao):
    estados = []
    for item in processos.values():
        if not isinstance(item, dict):
            continue
        fonte = (item.get("fontes") or {}).get(codigo) or {}
        if isinstance(fonte, dict):
            estados.append(str(fonte.get("status") or "SEM_REGISTRO"))
        else:
            estados.append("SEM_REGISTRO")

    contagem = Counter(estados)
    total = len(estados)
    concluidos = sum(
        quantidade for status, quantidade in contagem.items()
        if status.startswith("PESQUISADO")
    )
    falhas = total - concluidos

    if total == 0:
        status = "SEM_REGISTRO"
    elif falhas:
        status = "PENDENTE_OU_FALHA"
    else:
        status = "PESQUISADO"

    return {
        "atividade": descricao,
        "status": status,
        "total": total,
        "concluidos": concluidos,
        "pendentes": falhas,
        "situacoes": dict(contagem),
    }

def consolidar_dia(pasta):
    dia = pasta.name
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dia):
        return None
    try:
        dt.date.fromisoformat(dia)
    except ValueError:
        return None

    grade = ler_json(pasta / "grade" / (dia + ".json"))
    resumo = ler_json(pasta / "resumo_execucao.json")
    evidencia = ler_json(
        pasta / "evidencias" / "dou_inlabs_palavras_chave.json"
    )
    if grade is None and resumo is None and evidencia is None:
        return None

    processos = (grade or {}).get("processos") or {}
    if not isinstance(processos, dict):
        processos = {}

    atividades = [
        consolidar_fonte(processos, codigo, nome)
        for codigo, nome in FONTES.items()
    ]

    palavras = (resumo or {}).get("palavras_chave_inlabs") or evidencia or {}
    status_palavras = str(
        palavras.get("status") or "SEM_REGISTRO"
    )
    atividades.append({
        "atividade": "INLABS - Palavras-chave",
        "status": status_palavras,
        "erro": palavras.get("erro"),
    })

    comprovante = ler_json(
        pasta / ("comprovante_relatorio_" + dia + ".json")
    )
    relatorio_gerado = False

    if comprovante and comprovante.get("status") == "GERADO":
        caminho = pasta / ("relatorio_diario_" + dia + ".txt")
        if caminho.is_file():
            digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
            relatorio_gerado = (
                digest == comprovante.get("sha256")
                and comprovante.get("data") == dia
                and comprovante.get("cobertura_geral") == "PARCIAL"
            )

    atividades.append({
        "atividade": "Relatorio diario de pesquisas",
        "status": (
            "GERADO" if relatorio_gerado
            else "GERACAO_NAO_CONFIRMADA"
        ),
    })

    email = (resumo or {}).get("email") or {}
    atividades.append({
        "atividade": "Envio do relatorio por e-mail",
        "status": str(email.get("status") or "NAO_CONFIRMADO"),
    })

    cobertura = (resumo or {}).get("cobertura_geral")
    if cobertura not in ("INTEGRAL", "PARCIAL"):
        cobertura = "NAO_CONFIRMADA"
        if (
            grade is not None
            and status_palavras == "NAO_FOI_POSSIVEL_PESQUISAR"
        ):
            cobertura = "PARCIAL"

    return {
        "data": dia,
        "tipo": "TESTE_DEV",
        "status": str((resumo or {}).get("status") or "REGISTROS_PARCIAIS"),
        "cobertura": cobertura,
        "email": str(email.get("status") or "NAO_CONFIRMADO"),
        "atividades": atividades,
    }

def historico():
    meses = {}
    if BASE.is_dir():
        for pasta in BASE.iterdir():
            if not pasta.is_dir():
                continue
            registro = consolidar_dia(pasta)
            if registro:
                chave = registro["data"][:7]
                meses.setdefault(chave, []).append(registro)

    resultado = []
    for mes in sorted(meses, reverse=True):
        dias = sorted(
            meses[mes], key=lambda item: item["data"], reverse=True
        )
        resultado.append({
            "mes": mes,
            "quantidade_dias": len(dias),
            "dias": dias,
        })
    return {"ambiente": "DEV", "meses": resultado}

if __name__ == "__main__":
    dados = historico()
    for mes in dados["meses"]:
        print("MES:", mes["mes"], "DIAS:", mes["quantidade_dias"])
        for dia in mes["dias"]:
            print(
                " DATA:", dia["data"],
                "COBERTURA:", dia["cobertura"],
                "EMAIL:", dia["email"],
            )
            for atividade in dia["atividades"]:
                print(
                    "  -", atividade["atividade"],
                    ":", atividade["status"]
                )
    print("LEITURA_CONCLUIDA")
    print("EMAIL_ENVIADO: NAO")
