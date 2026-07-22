# ============================================================
# RUNNER — Pesquisa exata de processos no DOU em 2026
# Modo: sessão única INLABS
#
# Regras:
# - cobertura INLABS confirmada a partir de 2026-03-23;
# - mantém somente uma sessão autenticada por execução;
# - repete apenas a autenticação inicial em caso de HTTP 502;
# - baixa/reutiliza todos os ZIPs do período na mesma sessão;
# - processa os arquivos localmente após a etapa de download;
# - pode ser executado sozinho ou chamado pelo runner oficial;
# - lê os processos da aba PROCESSOS, coluna PROCESSO, do palavras_chave.xlsx;
# - pesquisa somente números completos de processo, sem IA;
# - refaz a pesquisa textual em todo o acervo anual a cada execução;
# - pesquisa também os PDFs de pautas e atas da Dicol/Anvisa de 2026.
# ============================================================

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from backend.drivers.dou.comum.busca_diaria import (
    TIPOS_DOU,
    baixar_zip_secao,
    carregar_publicacoes_dos_zips,
    criar_sessao_inlabs,
    obter_credenciais_inlabs,
)
from backend.services.base_publicacoes_service import (
    montar_base_publicacoes,
    salvar_base_publicacoes,
)
from backend.services.pesquisa_processos_dou_service import (
    carregar_processos_planilha,
    pesquisar_processos_nos_registros,
    salvar_relatorios_pesquisa_processos,
)


# Carregada dinamicamente no início de cada execução.
PROCESSOS_PESQUISA: tuple[str, ...] = ()


# ============================================================
# CAMINHOS
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]
CAMINHO_PALAVRAS_CHAVE = (
    ROOT_DIR
    / "backend"
    / "config"
    / "finalidades"
    / "dou_diario"
    / "palavras_chave.xlsx"
)
DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"
BRUTO_DIR = DATA_DOU_DIR / "bruto"
INLABS_DIR = DATA_DOU_DIR / "inlabs"

PASTA_SAIDA = (
    DATA_DOU_DIR
    / "pesquisas"
    / "processos_2026"
)

PASTA_POR_DATA = PASTA_SAIDA / "por_data"
PASTA_ERROS = PASTA_SAIDA / "erros"
PASTA_DEBUG = PASTA_SAIDA / "debug"

CAMINHO_PROGRESSO = (
    PASTA_SAIDA
    / "progresso_processos_2026.json"
)

CAMINHO_MANIFESTO = (
    PASTA_SAIDA
    / "manifesto_download_processos_2026.json"
)

ANVISA_DICOL_DIR = PASTA_SAIDA / "anvisa_dicol"
ANVISA_PDFS_DIR = ANVISA_DICOL_DIR / "pdfs"
ANVISA_OCR_DIR = ANVISA_DICOL_DIR / "ocr"
ANVISA_DEBUG_DIR = ANVISA_DICOL_DIR / "debug"

CAMINHO_ANVISA_JSON = (
    PASTA_SAIDA
    / "resultado_processos_anvisa_dicol_2026.json"
)
CAMINHO_ANVISA_CSV = (
    PASTA_SAIDA
    / "resultado_processos_anvisa_dicol_2026.csv"
)
CAMINHO_ANVISA_TXT = (
    PASTA_SAIDA
    / "resultado_processos_anvisa_dicol_2026_resumo.txt"
)
CAMINHO_ANVISA_MANIFESTO = (
    PASTA_SAIDA
    / "manifesto_anvisa_dicol_2026.json"
)

CAMINHO_TODAS_FONTES_JSON = (
    PASTA_SAIDA
    / "resultado_processos_2026_todas_fontes.json"
)
CAMINHO_TODAS_FONTES_CSV = (
    PASTA_SAIDA
    / "resultado_processos_2026_todas_fontes.csv"
)
CAMINHO_TODAS_FONTES_TXT = (
    PASTA_SAIDA
    / "resultado_processos_2026_todas_fontes_resumo.txt"
)

ANVISA_FONTES = {
    "ANVISA_DICOL_ATAS": (
        "https://www.gov.br/anvisa/pt-br/composicao/"
        "diretoria-colegiada/reunioes-da-diretoria/atas/2026"
    ),
    "ANVISA_DICOL_PAUTAS": (
        "https://www.gov.br/anvisa/pt-br/composicao/"
        "diretoria-colegiada/reunioes-da-diretoria/pautas/2026"
    ),
}

for pasta in [
    BRUTO_DIR,
    INLABS_DIR,
    PASTA_SAIDA,
    PASTA_POR_DATA,
    PASTA_ERROS,
    PASTA_DEBUG,
    ANVISA_DICOL_DIR,
    ANVISA_PDFS_DIR,
    ANVISA_OCR_DIR,
    ANVISA_DEBUG_DIR,
]:
    pasta.mkdir(parents=True, exist_ok=True)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

DATA_INICIO_COBERTURA_INLABS = datetime.date(2026, 3, 23)
DATA_FIM_LIMITE = datetime.date(2026, 12, 31)

PAUSA_ENTRE_DATAS_PADRAO = 1.0
MAX_TENTATIVAS_LOGIN_PADRAO = 6
PAUSAS_LOGIN_SEGUNDOS = (15, 30, 45, 60, 90)

STATUS_COLETA_OK = "COLETA_OK"
STATUS_SEM_PUBLICACOES = "SEM_PUBLICACOES_CONFIRMADO"
STATUS_ERRO_COLETA = "ERRO_COLETA"
STATUS_FORA_COBERTURA = "FORA_DA_COBERTURA_INLABS"

ANVISA_TIMEOUT_SEGUNDOS = 60
ANVISA_MAX_TENTATIVAS_HTTP = 4
ANVISA_PAUSAS_HTTP = (5, 15, 30)


# ============================================================
# UTILITÁRIOS
# ============================================================

def agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def salvar_json(caminho: Path, payload: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    temporario.replace(caminho)


def carregar_json_seguro(
    caminho: Path,
    padrao: Any,
) -> Any:
    if not caminho.exists():
        return padrao

    try:
        return json.loads(
            caminho.read_text(encoding="utf-8")
        )
    except Exception:
        return padrao


def converter_data(valor: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {valor!r}. Use AAAA-MM-DD."
        ) from erro


def resolver_data_fim_padrao() -> datetime.date:
    return min(datetime.date.today(), DATA_FIM_LIMITE)


def carregar_processos_operacionais() -> tuple[str, ...]:
    processos = carregar_processos_planilha(
        caminho_planilha=CAMINHO_PALAVRAS_CHAVE,
        nome_aba="PROCESSOS",
        nome_coluna="PROCESSO",
    )

    print("=" * 80)
    print("PROCESSOS CARREGADOS DA PLANILHA")
    print("=" * 80)
    print(f"Planilha: {CAMINHO_PALAVRAS_CHAVE}")
    print("Aba: PROCESSOS")
    print("Coluna: PROCESSO")
    print(f"Total de processos: {len(processos)}")

    for processo in processos:
        print(f"- {processo}")

    print("=" * 80)
    return processos


def validar_periodo(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> None:
    if data_inicio > data_fim:
        raise ValueError(
            "A data inicial não pode ser maior que a data final."
        )

    if data_fim > datetime.date.today():
        raise ValueError(
            "A data final não pode ser futura."
        )

    if data_inicio.year != 2026 or data_fim.year != 2026:
        raise ValueError(
            "Este runner foi criado exclusivamente para 2026."
        )


def gerar_datas(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> list[datetime.date]:
    datas: list[datetime.date] = []
    data_atual = data_inicio

    while data_atual <= data_fim:
        datas.append(data_atual)
        data_atual += datetime.timedelta(days=1)

    return datas


def caminho_zip(
    data_execucao: datetime.date,
    secao: str,
) -> Path:
    return (
        INLABS_DIR
        / data_execucao.isoformat()
        / "zips"
        / f"{data_execucao.isoformat()}-{secao}.zip"
    )


def caminho_resumo_inlabs(
    data_execucao: datetime.date,
) -> Path:
    data_txt = data_execucao.isoformat()

    return (
        INLABS_DIR
        / data_txt
        / f"resumo_inlabs_{data_txt}.json"
    )


def caminho_resultado_data(
    data_execucao: datetime.date,
) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_{data_execucao.isoformat()}.json"
    )


def caminho_erro_data(
    data_execucao: datetime.date,
) -> Path:
    return (
        PASTA_ERROS
        / f"erro_processos_{data_execucao.isoformat()}.txt"
    )


def zip_valido_com_xml(caminho: Path) -> tuple[bool, int]:
    if not caminho.exists():
        return False, 0

    if not zipfile.is_zipfile(caminho):
        return False, 0

    try:
        with zipfile.ZipFile(caminho, "r") as zf:
            total_xml = sum(
                1
                for nome in zf.namelist()
                if nome.lower().endswith(".xml")
            )
        return total_xml > 0, total_xml
    except Exception:
        return False, 0


def salvar_preview_arquivo_invalido(
    data_execucao: datetime.date,
    secao: str,
    caminho: Path,
) -> str:
    if not caminho.exists():
        return ""

    destino = (
        PASTA_DEBUG
        / (
            f"resposta_invalida_"
            f"{data_execucao.isoformat()}_{secao}.txt"
        )
    )

    try:
        conteudo = caminho.read_bytes()[:12000]
        destino.write_bytes(conteudo)
        return str(destino)
    except Exception:
        return ""


# ============================================================
# RESULTADO DIÁRIO / PROGRESSO
# ============================================================

def payload_resultado_diario_valido(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    if payload.get("status") != "SUCESSO":
        return False

    validacao = payload.get("validacao_coleta", {})

    if not isinstance(validacao, dict):
        return False

    return validacao.get("status") in {
        STATUS_COLETA_OK,
        STATUS_SEM_PUBLICACOES,
    }


def resultado_diario_valido(
    data_execucao: datetime.date,
) -> bool:
    payload = carregar_json_seguro(
        caminho_resultado_data(data_execucao),
        padrao=None,
    )
    return payload_resultado_diario_valido(payload)


def inicializar_progresso(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> dict:
    return {
        "tipo_pesquisa": "PROCESSO_EXATO_SEM_IA",
        "modo_coleta": "SESSAO_UNICA_INLABS",
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "cobertura_inlabs_inicio": (
            DATA_INICIO_COBERTURA_INLABS.isoformat()
        ),
        "criado_em": agora_iso(),
        "atualizado_em": agora_iso(),
        "processos": list(PROCESSOS_PESQUISA),
        "datas": {},
    }


def carregar_ou_inicializar_progresso(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> dict:
    progresso = carregar_json_seguro(
        CAMINHO_PROGRESSO,
        padrao=None,
    )

    if not isinstance(progresso, dict):
        progresso = inicializar_progresso(
            data_inicio,
            data_fim,
        )

    progresso.setdefault("datas", {})
    progresso["processos"] = list(PROCESSOS_PESQUISA)
    progresso["data_inicio"] = data_inicio.isoformat()
    progresso["data_fim"] = data_fim.isoformat()
    progresso["atualizado_em"] = agora_iso()

    return progresso


def salvar_resultado_data(
    data_execucao: datetime.date,
    registros: list[dict],
    resultados: list[dict],
    validacao_coleta: dict,
) -> Path:
    caminho = caminho_resultado_data(data_execucao)

    payload = {
        "data_execucao": data_execucao.isoformat(),
        "status": "SUCESSO",
        "gerado_em": agora_iso(),
        "total_registros_base": len(registros),
        "total_resultados": len(resultados),
        "processos": list(PROCESSOS_PESQUISA),
        "validacao_coleta": validacao_coleta,
        "resultados": resultados,
    }

    salvar_json(caminho, payload)
    return caminho


# ============================================================
# DOWNLOAD EM SESSÃO ÚNICA
# ============================================================

def ler_resposta_textual(
    caminho: Path,
    limite_bytes: int = 50000,
) -> str:
    if not caminho.exists():
        return ""

    try:
        return caminho.read_bytes()[:limite_bytes].decode(
            "utf-8",
            errors="ignore",
        ).lower()
    except Exception:
        return ""


def diagnosticar_resposta_nao_zip(
    caminho: Path,
) -> str:
    """
    Distingue:
    - página autenticada do INLABS retornada quando o ZIP não existe;
    - página de login/sessão expirada;
    - erro de gateway/serviço;
    - conteúdo desconhecido.
    """

    texto = ler_resposta_textual(caminho)

    if not texto:
        return "RESPOSTA_VAZIA"

    marcadores_gateway = [
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "erro 502",
        "erro 503",
        "erro 504",
    ]

    if any(marcador in texto for marcador in marcadores_gateway):
        return "ERRO_SERVICO"

    eh_html = (
        "<!doctype html" in texto
        or "<html" in texto
    )

    sessao_ativa = (
        eh_html
        and "imprensa nacional - inlabs" in texto
        and "minha conta" in texto
        and "logout.php" in texto
    )

    if sessao_ativa:
        return "PAGINA_INLABS_AUTENTICADA_SEM_ARQUIVO"

    marcadores_login = [
        "login",
        "entrar",
        "senha",
        "password",
    ]

    if (
        eh_html
        and any(
            marcador in texto
            for marcador in marcadores_login
        )
        and "logout.php" not in texto
    ):
        return "SESSAO_NAO_AUTENTICADA"

    if eh_html:
        return "HTML_DESCONHECIDO"

    return "RESPOSTA_DESCONHECIDA"


def classificar_resultado_download(
    item: dict,
    caminho_arquivo: Path,
) -> tuple[str, str]:
    http_status = int(
        item.get("http_status") or 0
    )

    if http_status == 404:
        return "NAO_EXISTE_404", ""

    if http_status != 200:
        return "ERRO_HTTP", ""

    if caminho_arquivo.exists() and zipfile.is_zipfile(
        caminho_arquivo
    ):
        try:
            with zipfile.ZipFile(
                caminho_arquivo,
                "r",
            ) as zf:
                total_xml_real = sum(
                    1
                    for nome in zf.namelist()
                    if nome.lower().endswith(".xml")
                )
        except Exception:
            return "ZIP_CORROMPIDO", ""

        item["xml_total"] = total_xml_real

        if total_xml_real > 0:
            return "ZIP_VALIDO", ""

        return "ZIP_VAZIO_VALIDO", ""

    diagnostico = diagnosticar_resposta_nao_zip(
        caminho_arquivo
    )

    if (
        diagnostico
        == "PAGINA_INLABS_AUTENTICADA_SEM_ARQUIVO"
    ):
        return (
            "NAO_EXISTE_SESSAO_ATIVA",
            diagnostico,
        )

    if diagnostico in {
        "SESSAO_NAO_AUTENTICADA",
        "ERRO_SERVICO",
    }:
        return (
            "ERRO_SESSAO_OU_SERVICO",
            diagnostico,
        )

    return (
        "RESPOSTA_NAO_ZIP_DESCONHECIDA",
        diagnostico,
    )


def inspecionar_zip_local(
    caminho: Path,
) -> tuple[str, int]:
    if not caminho.exists():
        return "AUSENTE", 0

    if not zipfile.is_zipfile(caminho):
        return "INVALIDO", 0

    try:
        with zipfile.ZipFile(caminho, "r") as zf:
            total_xml = sum(
                1
                for nome in zf.namelist()
                if nome.lower().endswith(".xml")
            )
    except Exception:
        return "INVALIDO", 0

    if total_xml > 0:
        return "ZIP_VALIDO", total_xml

    return "ZIP_VAZIO_VALIDO", 0


def baixar_data_com_sessao(
    session,
    data_execucao: datetime.date,
    reusar_zips_validos: bool,
) -> dict:
    resultados: list[dict] = []

    for secao in TIPOS_DOU:
        zip_path = caminho_zip(
            data_execucao,
            secao,
        )

        if reusar_zips_validos:
            classificacao_local, total_xml = (
                inspecionar_zip_local(zip_path)
            )

            if classificacao_local in {
                "ZIP_VALIDO",
                "ZIP_VAZIO_VALIDO",
            }:
                resultados.append({
                    "secao": secao,
                    "nome_zip": zip_path.name,
                    "caminho_zip": str(zip_path),
                    "http_status": 200,
                    "salvo": True,
                    "tamanho_zip_bytes": (
                        zip_path.stat().st_size
                    ),
                    "xml_total": total_xml,
                    "erro": "",
                    "origem_download": (
                        "REUTILIZADO_LOCAL"
                    ),
                    "classificacao": (
                        classificacao_local
                    ),
                    "diagnostico_resposta": "",
                })

                print(
                    f"[REUTILIZADO] "
                    f"{zip_path.name} | "
                    f"classificacao="
                    f"{classificacao_local} | "
                    f"xml_total={total_xml}"
                )
                continue

        resultado = baixar_zip_secao(
            session=session,
            data_alvo=data_execucao,
            secao=secao,
        )

        resultado["origem_download"] = (
            "BAIXADO_SESSAO_UNICA"
        )

        classificacao, diagnostico = (
            classificar_resultado_download(
                resultado,
                zip_path,
            )
        )

        resultado["classificacao"] = (
            classificacao
        )
        resultado["diagnostico_resposta"] = (
            diagnostico
        )

        if classificacao in {
            "NAO_EXISTE_SESSAO_ATIVA",
            "ERRO_SESSAO_OU_SERVICO",
            "RESPOSTA_NAO_ZIP_DESCONHECIDA",
            "ZIP_CORROMPIDO",
        }:
            preview = salvar_preview_arquivo_invalido(
                data_execucao=data_execucao,
                secao=secao,
                caminho=zip_path,
            )
            resultado[
                "arquivo_debug_resposta"
            ] = preview

            # A resposta HTML/textual não pode permanecer
            # com extensão .zip para uma execução futura.
            try:
                if zip_path.exists():
                    zip_path.unlink()
            except Exception:
                pass

        resultados.append(resultado)

    validos = [
        item
        for item in resultados
        if item.get("classificacao")
        == "ZIP_VALIDO"
    ]

    vazios_validos = [
        item
        for item in resultados
        if item.get("classificacao")
        == "ZIP_VAZIO_VALIDO"
    ]

    inexistentes_404 = [
        item
        for item in resultados
        if item.get("classificacao")
        == "NAO_EXISTE_404"
    ]

    inexistentes_sessao_ativa = [
        item
        for item in resultados
        if item.get("classificacao")
        == "NAO_EXISTE_SESSAO_ATIVA"
    ]

    ausentes = (
        inexistentes_404
        + inexistentes_sessao_ativa
    )

    falhas = [
        item
        for item in resultados
        if item.get("classificacao")
        not in {
            "ZIP_VALIDO",
            "ZIP_VAZIO_VALIDO",
            "NAO_EXISTE_404",
            "NAO_EXISTE_SESSAO_ATIVA",
        }
    ]

    if falhas:
        status = STATUS_ERRO_COLETA
        mensagem = (
            "Uma ou mais edições apresentaram "
            "falha de sessão, serviço, HTTP ou "
            "resposta não reconhecida."
        )

    elif validos:
        status = STATUS_COLETA_OK
        mensagem = (
            "Coleta validada com um ou mais "
            "ZIPs oficiais contendo XMLs."
        )

    elif (
        len(ausentes) + len(vazios_validos)
        == len(TIPOS_DOU)
    ):
        status = STATUS_SEM_PUBLICACOES
        mensagem = (
            "Ausência de publicações confirmada: "
            "todas as edições estavam ausentes ou "
            "foram entregues em ZIP oficial vazio."
        )

    else:
        status = STATUS_ERRO_COLETA
        mensagem = (
            "A coleta não produziu XMLs e também "
            "não comprovou ausência das seis edições."
        )

    resumo = {
        "data": data_execucao.isoformat(),
        "fonte": "INLABS",
        "modo_coleta": "SESSAO_UNICA",
        "coletado_em": agora_iso(),
        "status": status,
        "mensagem": mensagem,
        "total_zips_validos": len(validos),
        "total_zips_vazios_validos": (
            len(vazios_validos)
        ),
        "total_secoes_404": (
            len(inexistentes_404)
        ),
        "total_secoes_sem_arquivo_sessao_ativa": (
            len(inexistentes_sessao_ativa)
        ),
        "total_secoes_ausentes": len(ausentes),
        "total_falhas": len(falhas),
        "total_xml": sum(
            int(item.get("xml_total") or 0)
            for item in validos
        ),
        "resultados": resultados,
    }

    salvar_json(
        caminho_resumo_inlabs(data_execucao),
        resumo,
    )

    return resumo


def criar_sessao_inlabs_com_tentativas(
    email: str,
    senha: str,
    max_tentativas: int,
):
    """
    Faz tentativas apenas para obter a sessão inicial.

    Depois do primeiro login bem-sucedido, a mesma sessão é usada
    em todos os downloads da execução.
    """

    ultimo_erro: Exception | None = None

    for tentativa in range(
        1,
        max_tentativas + 1,
    ):
        try:
            if tentativa > 1:
                print(
                    f"[LOGIN] Tentativa "
                    f"{tentativa}/{max_tentativas}"
                )

            return criar_sessao_inlabs(
                email=email,
                senha=senha,
            )

        except Exception as erro:
            ultimo_erro = erro

            if tentativa >= max_tentativas:
                break

            indice_pausa = min(
                tentativa - 1,
                len(PAUSAS_LOGIN_SEGUNDOS) - 1,
            )
            pausa = (
                PAUSAS_LOGIN_SEGUNDOS[
                    indice_pausa
                ]
            )

            print(
                f"[AVISO] Login INLABS falhou: "
                f"{erro}"
            )
            print(
                f"[AVISO] Nova tentativa em "
                f"{pausa} segundos."
            )

            time.sleep(pausa)

    if ultimo_erro is not None:
        raise ultimo_erro

    raise RuntimeError(
        "Falha ao criar sessão INLABS."
    )


def executar_download_em_sessao_unica(
    datas: list[datetime.date],
    progresso: dict,
    reusar_zips_validos: bool,
    pausa_entre_datas: float,
    max_tentativas_login: int,
) -> dict:
    print("=" * 80)
    print("FASE 1 — DOWNLOAD INLABS COM SESSÃO ÚNICA")
    print("=" * 80)
    print(f"Datas selecionadas: {len(datas)}")
    print("Sessões autenticadas previstas: 1")
    print(
        "Tentativas máximas para obter a sessão: "
        f"{max_tentativas_login}"
    )
    print("=" * 80)

    email, senha = obter_credenciais_inlabs()
    session = criar_sessao_inlabs_com_tentativas(
        email=email,
        senha=senha,
        max_tentativas=max_tentativas_login,
    )

    manifesto = {
        "modo": "SESSAO_UNICA_INLABS",
        "inicio": agora_iso(),
        "fim": None,
        "total_logins": 1,
        "datas": {},
    }

    try:
        for indice, data_execucao in enumerate(
            datas,
            start=1,
        ):
            data_txt = data_execucao.isoformat()

            print("=" * 80)
            print(
                f"DOWNLOAD {indice}/{len(datas)} | {data_txt}"
            )
            print("=" * 80)

            try:
                resumo = baixar_data_com_sessao(
                    session=session,
                    data_execucao=data_execucao,
                    reusar_zips_validos=(
                        reusar_zips_validos
                    ),
                )

                manifesto["datas"][data_txt] = resumo

                progresso.setdefault("datas", {}).setdefault(
                    data_txt,
                    {},
                )
                progresso["datas"][data_txt][
                    "status_download"
                ] = resumo.get("status")
                progresso["datas"][data_txt][
                    "resumo_download"
                ] = resumo
                progresso["datas"][data_txt][
                    "atualizado_em"
                ] = agora_iso()

                # Se nenhuma seção foi obtida e todas falharam, a sessão
                # ou o serviço INLABS provavelmente ficou indisponível.
                # Interrompe sem fazer novo login nesta mesma execução.
                if (
                    resumo.get("status") == STATUS_ERRO_COLETA
                    and int(resumo.get("total_zips_validos") or 0) == 0
                    and int(resumo.get("total_secoes_ausentes") or 0) == 0
                    and int(resumo.get("total_zips_vazios_validos") or 0) == 0
                    and int(resumo.get("total_falhas") or 0) > 0
                ):
                    manifesto["interrompido"] = True
                    manifesto["motivo_interrupcao"] = (
                        "Sessão ou serviço INLABS indisponível. "
                        "A execução foi interrompida sem realizar novo login."
                    )
                    progresso["interrompido"] = True
                    progresso["motivo_interrupcao"] = (
                        manifesto["motivo_interrupcao"]
                    )
                    progresso["atualizado_em"] = agora_iso()
                    salvar_json(CAMINHO_PROGRESSO, progresso)

                    print("=" * 80)
                    print("DOWNLOAD INTERROMPIDO POR PROTEÇÃO")
                    print("=" * 80)
                    print(manifesto["motivo_interrupcao"])
                    print(
                        "Os ZIPs válidos já baixados foram preservados. "
                        "Na próxima execução, eles serão reutilizados."
                    )
                    print("=" * 80)
                    break

            except Exception as erro:
                traceback_txt = traceback.format_exc()
                caminho_erro = caminho_erro_data(
                    data_execucao
                )
                caminho_erro.write_text(
                    traceback_txt,
                    encoding="utf-8",
                )

                resumo_erro = {
                    "data": data_txt,
                    "status": STATUS_ERRO_COLETA,
                    "mensagem": str(erro),
                    "arquivo_erro": str(caminho_erro),
                }

                manifesto["datas"][data_txt] = resumo_erro

                progresso.setdefault("datas", {}).setdefault(
                    data_txt,
                    {},
                )
                progresso["datas"][data_txt][
                    "status_download"
                ] = STATUS_ERRO_COLETA
                progresso["datas"][data_txt][
                    "resumo_download"
                ] = resumo_erro
                progresso["datas"][data_txt][
                    "atualizado_em"
                ] = agora_iso()

            progresso["atualizado_em"] = agora_iso()
            salvar_json(CAMINHO_PROGRESSO, progresso)

            if (
                pausa_entre_datas > 0
                and indice < len(datas)
            ):
                time.sleep(pausa_entre_datas)

    finally:
        try:
            session.close()
        except Exception:
            pass

        manifesto["fim"] = agora_iso()
        salvar_json(CAMINHO_MANIFESTO, manifesto)

    return manifesto


# ============================================================
# PROCESSAMENTO LOCAL
# ============================================================

def salvar_artefatos_base_padrao(
    data_execucao: datetime.date,
    publicacoes_validas: list[dict],
) -> list[dict]:
    data_txt = data_execucao.isoformat()

    payload_publicacoes = {
        "data": data_txt,
        "fonte": "INLABS",
        "origem": "INLABS",
        "gerado_em": agora_iso(),
        "status_busca": "COM_PUBLICACOES",
        "total_publicacoes": len(publicacoes_validas),
        "total_links": len(publicacoes_validas),
        "publicacoes": publicacoes_validas,
        "links": publicacoes_validas,
    }

    salvar_json(
        BRUTO_DIR / f"publicacoes_{data_txt}.json",
        payload_publicacoes,
    )

    salvar_json(
        BRUTO_DIR / f"links_dou_{data_txt}.json",
        payload_publicacoes,
    )

    registros = montar_base_publicacoes(
        payload_publicacoes
    )

    salvar_base_publicacoes(
        data_referencia=data_txt,
        registros=registros,
    )

    return registros


def processar_data_local(
    data_execucao: datetime.date,
    resumo_download: dict,
) -> dict:
    status_download = resumo_download.get("status")

    if status_download == STATUS_SEM_PUBLICACOES:
        registros: list[dict] = []
        resultados: list[dict] = []

        caminho_salvo = salvar_resultado_data(
            data_execucao=data_execucao,
            registros=registros,
            resultados=resultados,
            validacao_coleta=resumo_download,
        )

        return {
            "status": "SUCESSO",
            "status_download": status_download,
            "total_registros_base": 0,
            "total_resultados": 0,
            "arquivo_resultado": str(caminho_salvo),
        }

    if status_download != STATUS_COLETA_OK:
        raise RuntimeError(
            f"Data não pode ser processada: "
            f"status_download={status_download}"
        )

    publicacoes = carregar_publicacoes_dos_zips(
        data_execucao
    )

    publicacoes_validas = [
        item
        for item in publicacoes
        if isinstance(item, dict)
        and item.get("texto_integral")
    ]

    if not publicacoes_validas:
        raise RuntimeError(
            "A coleta foi marcada como válida, mas nenhum "
            "texto integral foi extraído dos ZIPs."
        )

    registros = salvar_artefatos_base_padrao(
        data_execucao=data_execucao,
        publicacoes_validas=publicacoes_validas,
    )

    resultados = pesquisar_processos_nos_registros(
        registros=registros,
        processos=PROCESSOS_PESQUISA,
    )

    caminho_salvo = salvar_resultado_data(
        data_execucao=data_execucao,
        registros=registros,
        resultados=resultados,
        validacao_coleta=resumo_download,
    )

    return {
        "status": "SUCESSO",
        "status_download": status_download,
        "total_registros_base": len(registros),
        "total_resultados": len(resultados),
        "arquivo_resultado": str(caminho_salvo),
    }


def executar_processamento_local(
    datas: list[datetime.date],
    manifesto: dict,
    progresso: dict,
) -> None:
    print("=" * 80)
    print("FASE 2 — PROCESSAMENTO LOCAL DOS ZIPs")
    print("=" * 80)

    for indice, data_execucao in enumerate(
        datas,
        start=1,
    ):
        data_txt = data_execucao.isoformat()
        resumo_download = manifesto.get(
            "datas",
            {},
        ).get(data_txt, {})

        print(
            f"[{indice}/{len(datas)}] "
            f"{data_txt} | "
            f"{resumo_download.get('status')}"
        )

        if (
            resumo_download.get("status")
            == STATUS_ERRO_COLETA
        ):
            progresso.setdefault("datas", {}).setdefault(
                data_txt,
                {},
            )
            progresso["datas"][data_txt]["status"] = (
                STATUS_ERRO_COLETA
            )
            progresso["datas"][data_txt][
                "atualizado_em"
            ] = agora_iso()
            salvar_json(CAMINHO_PROGRESSO, progresso)
            continue

        try:
            resultado = processar_data_local(
                data_execucao=data_execucao,
                resumo_download=resumo_download,
            )

            progresso.setdefault("datas", {})[
                data_txt
            ] = {
                **progresso.get("datas", {}).get(
                    data_txt,
                    {},
                ),
                **resultado,
                "atualizado_em": agora_iso(),
            }

        except Exception as erro:
            traceback_txt = traceback.format_exc()
            caminho_erro = caminho_erro_data(
                data_execucao
            )
            caminho_erro.write_text(
                traceback_txt,
                encoding="utf-8",
            )

            progresso.setdefault("datas", {})[
                data_txt
            ] = {
                **progresso.get("datas", {}).get(
                    data_txt,
                    {},
                ),
                "status": "ERRO_PROCESSAMENTO",
                "erro": str(erro),
                "arquivo_erro": str(caminho_erro),
                "atualizado_em": agora_iso(),
            }

        progresso["atualizado_em"] = agora_iso()
        salvar_json(CAMINHO_PROGRESSO, progresso)


# ============================================================
# ANVISA — PAUTAS E ATAS DA DIRETORIA COLEGIADA
# ============================================================

def importar_dependencias_anvisa():
    """
    Dependências carregadas somente quando a fonte Anvisa é executada.
    """

    try:
        import requests
    except ImportError as erro:
        raise RuntimeError(
            "A pesquisa Anvisa requer o pacote requests."
        ) from erro

    try:
        from bs4 import BeautifulSoup
    except ImportError as erro:
        raise RuntimeError(
            "A pesquisa Anvisa requer o pacote beautifulsoup4."
        ) from erro

    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as erro:
            raise RuntimeError(
                "A pesquisa dos PDFs requer pypdf ou PyPDF2."
            ) from erro

    return requests, BeautifulSoup, PdfReader


def criar_sessao_http_anvisa():
    requests, _, _ = importar_dependencias_anvisa()

    sessao = requests.Session()
    sessao.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/130 Safari/537.36 "
            "PesquisaProcessosDOU/2026"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    })

    return sessao


def obter_http_com_tentativas(
    sessao,
    url: str,
    *,
    aceitar_pdf: bool = False,
):
    ultimo_erro: Exception | None = None

    for tentativa in range(
        1,
        ANVISA_MAX_TENTATIVAS_HTTP + 1,
    ):
        try:
            resposta = sessao.get(
                url,
                timeout=ANVISA_TIMEOUT_SEGUNDOS,
                allow_redirects=True,
            )

            if resposta.status_code == 200:
                if aceitar_pdf:
                    conteudo_tipo = str(
                        resposta.headers.get(
                            "Content-Type",
                            "",
                        )
                    ).lower()

                    if (
                        "application/pdf" in conteudo_tipo
                        or resposta.content.startswith(b"%PDF")
                    ):
                        return resposta

                else:
                    return resposta

            if resposta.status_code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                resposta.raise_for_status()

            raise RuntimeError(
                f"HTTP={resposta.status_code} ao acessar {url}"
            )

        except Exception as erro:
            ultimo_erro = erro

            if tentativa >= ANVISA_MAX_TENTATIVAS_HTTP:
                break

            indice = min(
                tentativa - 1,
                len(ANVISA_PAUSAS_HTTP) - 1,
            )
            pausa = ANVISA_PAUSAS_HTTP[indice]

            print(
                f"[ANVISA] Falha HTTP: {erro}"
            )
            print(
                f"[ANVISA] Nova tentativa em {pausa} segundos."
            )
            time.sleep(pausa)

    if ultimo_erro is not None:
        raise ultimo_erro

    raise RuntimeError(
        f"Falha HTTP sem exceção registrada: {url}"
    )


def normalizar_url_anvisa(url: str) -> str:
    url_sem_fragmento, _ = urldefrag(url)
    url_normalizada = url_sem_fragmento.rstrip("/")

    # No portal gov.br/Plone, ".pdf/view" é uma página HTML de
    # visualização do mesmo PDF. O arquivo direto termina em ".pdf".
    if url_normalizada.lower().endswith(".pdf/view"):
        url_normalizada = url_normalizada[:-5]

    return url_normalizada


def url_no_diretorio_anvisa(
    url: str,
    url_raiz: str,
) -> bool:
    url_normalizada = normalizar_url_anvisa(url)
    raiz_normalizada = normalizar_url_anvisa(url_raiz)

    return (
        url_normalizada == raiz_normalizada
        or url_normalizada.startswith(
            raiz_normalizada + "/"
        )
    )


def resposta_eh_pdf(resposta) -> bool:
    tipo = str(
        resposta.headers.get(
            "Content-Type",
            "",
        )
    ).lower()

    return (
        "application/pdf" in tipo
        or resposta.content.startswith(b"%PDF")
    )


def extrair_links_html_anvisa(
    html_texto: str,
    url_base: str,
) -> list[dict]:
    _, BeautifulSoup, _ = importar_dependencias_anvisa()

    soup = BeautifulSoup(
        html_texto,
        "html.parser",
    )

    links: list[dict] = []
    vistos: set[str] = set()

    for ancora in soup.find_all(
        "a",
        href=True,
    ):
        href = str(
            ancora.get("href") or ""
        ).strip()

        if not href:
            continue

        url = normalizar_url_anvisa(
            urljoin(url_base, href)
        )

        if url in vistos:
            continue

        vistos.add(url)

        titulo = " ".join(
            ancora.get_text(
                " ",
                strip=True,
            ).split()
        )

        links.append({
            "url": url,
            "titulo": titulo,
        })

    return links


def descobrir_pdfs_fonte_anvisa(
    sessao,
    nome_fonte: str,
    url_raiz: str,
) -> list[dict]:
    print("=" * 80)
    print(
        f"[ANVISA] DESCOBRINDO DOCUMENTOS — {nome_fonte}"
    )
    print("=" * 80)

    resposta_raiz = obter_http_com_tentativas(
        sessao,
        url_raiz,
    )

    links_raiz = extrair_links_html_anvisa(
        resposta_raiz.text,
        resposta_raiz.url,
    )

    candidatos = [
        item
        for item in links_raiz
        if url_no_diretorio_anvisa(
            item["url"],
            url_raiz,
        )
        and normalizar_url_anvisa(
            item["url"]
        )
        != normalizar_url_anvisa(
            url_raiz
        )
    ]

    documentos: list[dict] = []
    pdfs_vistos: set[str] = set()

    for indice, candidato in enumerate(
        candidatos,
        start=1,
    ):
        url_candidato = candidato["url"]

        try:
            resposta = obter_http_com_tentativas(
                sessao,
                url_candidato,
            )
        except Exception as erro:
            print(
                f"[ANVISA] Não foi possível abrir "
                f"{url_candidato}: {erro}"
            )
            continue

        if resposta_eh_pdf(resposta):
            url_pdf = normalizar_url_anvisa(
                resposta.url
            )

            if url_pdf not in pdfs_vistos:
                pdfs_vistos.add(url_pdf)
                documentos.append({
                    "fonte": nome_fonte,
                    "titulo": (
                        candidato.get("titulo")
                        or Path(
                            urlparse(url_pdf).path
                        ).name
                    ),
                    "url_item": url_candidato,
                    "url_pdf": url_pdf,
                })

            continue

        links_item = extrair_links_html_anvisa(
            resposta.text,
            resposta.url,
        )

        for link in links_item:
            url_link = link["url"]
            url_lower = unquote(
                urlparse(url_link).path
            ).lower()

            parece_pdf = (
                ".pdf" in url_lower
                or "@@download/file" in url_lower
            )

            if not parece_pdf:
                continue

            url_pdf = normalizar_url_anvisa(
                url_link
            )

            if url_pdf in pdfs_vistos:
                continue

            pdfs_vistos.add(url_pdf)
            documentos.append({
                "fonte": nome_fonte,
                "titulo": (
                    link.get("titulo")
                    or candidato.get("titulo")
                    or Path(
                        urlparse(url_pdf).path
                    ).name
                ),
                "url_item": url_candidato,
                "url_pdf": url_pdf,
            })

    documentos.sort(
        key=lambda item: (
            item.get("fonte") or "",
            item.get("titulo") or "",
            item.get("url_pdf") or "",
        )
    )

    print(
        f"[ANVISA] {nome_fonte}: "
        f"{len(documentos)} PDF(s) descoberto(s)."
    )

    return documentos


def nome_arquivo_pdf_anvisa(
    documento: dict,
) -> str:
    url_pdf = str(
        documento.get("url_pdf") or ""
    )

    nome_url = unquote(
        Path(
            urlparse(url_pdf).path
        ).name
    )

    if (
        not nome_url
        or nome_url in {
            "file",
            "@@download",
        }
    ):
        nome_url = (
            documento.get("titulo")
            or "documento_anvisa"
        )

    nome_sem_extensao = re.sub(
        r"\.pdf$",
        "",
        nome_url,
        flags=re.IGNORECASE,
    )

    nome_limpo = unicodedata.normalize(
        "NFKD",
        nome_sem_extensao,
    )
    nome_limpo = "".join(
        caractere
        for caractere in nome_limpo
        if not unicodedata.combining(
            caractere
        )
    )
    nome_limpo = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        nome_limpo,
    ).strip("._-")

    if not nome_limpo:
        nome_limpo = "documento_anvisa"

    hash_url = hashlib.sha256(
        url_pdf.encode("utf-8")
    ).hexdigest()[:12]

    return (
        f"{nome_limpo[:120]}_{hash_url}.pdf"
    )


def baixar_pdf_anvisa(
    sessao,
    documento: dict,
    *,
    forcar_download: bool,
) -> Path:
    fonte = str(
        documento.get("fonte")
        or "ANVISA"
    )
    subpasta = (
        "atas"
        if "ATAS" in fonte
        else "pautas"
    )

    pasta = ANVISA_PDFS_DIR / subpasta
    pasta.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho = pasta / nome_arquivo_pdf_anvisa(
        documento
    )

    if (
        caminho.exists()
        and caminho.stat().st_size > 0
        and not forcar_download
    ):
        with caminho.open("rb") as arquivo:
            assinatura = arquivo.read(4)

        if assinatura == b"%PDF":
            documento["origem_arquivo"] = (
                "REUTILIZADO_LOCAL"
            )
            documento["arquivo_pdf"] = str(
                caminho
            )
            return caminho

    resposta = obter_http_com_tentativas(
        sessao,
        str(documento["url_pdf"]),
        aceitar_pdf=True,
    )

    if not resposta_eh_pdf(resposta):
        raise RuntimeError(
            "O endereço não retornou um PDF válido: "
            f"{documento['url_pdf']}"
        )

    temporario = caminho.with_suffix(
        ".pdf.tmp"
    )
    temporario.write_bytes(
        resposta.content
    )
    temporario.replace(caminho)

    documento["origem_arquivo"] = (
        "BAIXADO"
    )
    documento["arquivo_pdf"] = str(
        caminho
    )

    return caminho


def normalizar_texto_pdf_anvisa(
    texto: str,
) -> str:
    texto = unicodedata.normalize(
        "NFKC",
        texto or "",
    )
    texto = texto.replace(
        "\u00a0",
        " ",
    )
    return texto


def padroes_processos_anvisa() -> dict:
    padroes = {}

    for processo in PROCESSOS_PESQUISA:
        digitos = re.sub(
            r"\D",
            "",
            processo,
        )

        if len(digitos) != 17:
            continue

        grupos = (
            digitos[0:5],
            digitos[5:11],
            digitos[11:15],
            digitos[15:17],
        )

        estrito = re.compile(
            rf"(?<!\d)"
            rf"{grupos[0]}[\s.\-_/]{{0,12}}"
            rf"{grupos[1]}[\s.\-_/]{{0,12}}"
            rf"{grupos[2]}[\s.\-_/]{{0,12}}"
            rf"{grupos[3]}"
            rf"(?!\d)"
        )

        amplo = re.compile(
            rf"(?<!\d)"
            rf"{grupos[0]}\D{{0,40}}"
            rf"{grupos[1]}\D{{0,40}}"
            rf"{grupos[2]}\D{{0,40}}"
            rf"{grupos[3]}"
            rf"(?!\d)"
        )

        padroes[processo] = {
            "estrito": estrito,
            "amplo": amplo,
        }

    return padroes


def recortar_contexto_anvisa(
    texto: str,
    inicio: int,
    fim: int,
    margem: int = 220,
) -> str:
    esquerda = max(
        0,
        inicio - margem,
    )
    direita = min(
        len(texto),
        fim + margem,
    )

    trecho = re.sub(
        r"\s+",
        " ",
        texto[esquerda:direita],
    ).strip()

    if esquerda > 0:
        trecho = "..." + trecho

    if direita < len(texto):
        trecho += "..."

    return trecho


def pesquisar_processos_pdf_anvisa_sem_ocr(
    caminho_pdf: Path,
    documento: dict,
) -> tuple[list[dict], dict]:
    _, _, PdfReader = importar_dependencias_anvisa()

    padroes = padroes_processos_anvisa()
    resultados: list[dict] = []

    leitor = PdfReader(
        str(caminho_pdf)
    )

    paginas_com_texto = 0
    caracteres_extraidos = 0
    erros_paginas = 0

    for numero_pagina, pagina in enumerate(
        leitor.pages,
        start=1,
    ):
        try:
            texto = normalizar_texto_pdf_anvisa(
                pagina.extract_text() or ""
            )
        except Exception:
            erros_paginas += 1
            continue

        if texto.strip():
            paginas_com_texto += 1
            caracteres_extraidos += len(texto)

        for processo, regras in padroes.items():
            encontrados_estritos = list(
                regras["estrito"].finditer(
                    texto
                )
            )

            if encontrados_estritos:
                ocorrencias = [
                    ("EXATO", item)
                    for item in encontrados_estritos
                ]
            else:
                ocorrencias = [
                    ("AMPLO_REVISAR", item)
                    for item in regras[
                        "amplo"
                    ].finditer(texto)
                ]

            for tipo_match, ocorrencia in ocorrencias:
                resultados.append({
                    "fonte": documento.get(
                        "fonte"
                    ),
                    "processo": processo,
                    "tipo_match": tipo_match,
                    "titulo": documento.get(
                        "titulo"
                    ),
                    "pagina_pdf": numero_pagina,
                    "valor_encontrado": (
                        ocorrencia.group(0)
                    ),
                    "trecho": (
                        recortar_contexto_anvisa(
                            texto,
                            ocorrencia.start(),
                            ocorrencia.end(),
                        )
                    ),
                    "url_item": documento.get(
                        "url_item"
                    ),
                    "url_pdf": documento.get(
                        "url_pdf"
                    ),
                    "arquivo_pdf": str(
                        caminho_pdf
                    ),
                    "chave_resultado": (
                        f"{processo}|"
                        f"{documento.get('url_pdf')}|"
                        f"{numero_pagina}|"
                        f"{ocorrencia.start()}"
                    ),
                })

    diagnostico = {
        "total_paginas": len(
            leitor.pages
        ),
        "paginas_com_texto": paginas_com_texto,
        "caracteres_extraidos": (
            caracteres_extraidos
        ),
        "erros_paginas": erros_paginas,
        "status_leitura": (
            "TEXTO_EXTRAIDO"
            if paginas_com_texto > 0
            else "SEM_TEXTO_EXTRAIVEL"
        ),
    }

    return resultados, diagnostico



def caminho_pdf_ocr_anvisa(
    caminho_pdf: Path,
    documento: dict,
) -> Path:
    fonte = str(
        documento.get("fonte")
        or "ANVISA"
    )

    subpasta = (
        "atas"
        if "ATAS" in fonte
        else "pautas"
    )

    pasta = ANVISA_OCR_DIR / subpasta
    pasta.mkdir(
        parents=True,
        exist_ok=True,
    )

    return pasta / (
        f"{caminho_pdf.stem}_ocr.pdf"
    )


def executar_ocr_pdf_anvisa(
    caminho_pdf: Path,
    documento: dict,
) -> tuple[Path, dict]:
    """
    Aplica OCR somente quando o PDF não possui texto extraível.

    Usa OCRmyPDF no mesmo ambiente Python. No Windows, OCRmyPDF
    procura Tesseract e Ghostscript no Registro e em Program Files.
    """

    caminho_ocr = caminho_pdf_ocr_anvisa(
        caminho_pdf=caminho_pdf,
        documento=documento,
    )

    forcar_ocr = bool(
        documento.get("_forcar_ocr")
    )

    if (
        caminho_ocr.exists()
        and caminho_ocr.stat().st_size > 0
        and not forcar_ocr
    ):
        try:
            with caminho_ocr.open("rb") as arquivo:
                assinatura = arquivo.read(4)

            if assinatura == b"%PDF":
                return caminho_ocr, {
                    "status": "REUTILIZADO",
                    "arquivo_ocr": str(caminho_ocr),
                }
        except Exception:
            pass

    caminho_temporario = caminho_ocr.with_suffix(
        ".pdf.tmp"
    )

    try:
        if caminho_temporario.exists():
            caminho_temporario.unlink()
    except Exception:
        pass

    comando = [
        sys.executable,
        "-m",
        "ocrmypdf",
        "--language",
        "por",
        "--deskew",
        "--rotate-pages",
        "--output-type",
        "pdf",
        "--optimize",
        "1",
        str(caminho_pdf),
        str(caminho_temporario),
    ]

    print(
        f"[ANVISA/OCR] Aplicando OCR: "
        f"{caminho_pdf.name}"
    )

    try:
        processo = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except FileNotFoundError as erro:
        raise RuntimeError(
            "Não foi possível executar o OCR. "
            "Instale o pacote ocrmypdf, o Tesseract OCR "
            "e o Ghostscript."
        ) from erro
    except subprocess.TimeoutExpired as erro:
        raise RuntimeError(
            "O OCR excedeu o limite de 30 minutos."
        ) from erro

    diagnostico = {
        "status": (
            "SUCESSO"
            if processo.returncode == 0
            else "ERRO"
        ),
        "codigo_retorno": processo.returncode,
        "stdout": processo.stdout[-12000:],
        "stderr": processo.stderr[-12000:],
        "arquivo_ocr": str(caminho_ocr),
        "comando": comando,
    }

    caminho_log = (
        ANVISA_DEBUG_DIR
        / f"ocr_{caminho_pdf.stem}.json"
    )
    salvar_json(
        caminho_log,
        diagnostico,
    )
    diagnostico["arquivo_log"] = str(
        caminho_log
    )

    if processo.returncode != 0:
        mensagem = (
            processo.stderr.strip()
            or processo.stdout.strip()
            or "OCRmyPDF retornou erro sem mensagem."
        )

        raise RuntimeError(
            "Falha no OCR do PDF: "
            f"{mensagem[-2000:]}"
        )

    if (
        not caminho_temporario.exists()
        or caminho_temporario.stat().st_size <= 0
    ):
        raise RuntimeError(
            "O OCR terminou sem gerar um PDF válido."
        )

    caminho_temporario.replace(
        caminho_ocr
    )

    return caminho_ocr, diagnostico


def pesquisar_processos_pdf_anvisa(
    caminho_pdf: Path,
    documento: dict,
) -> tuple[list[dict], dict]:
    """
    Primeiro tenta extração textual normal. Quando o PDF é imagem,
    aplica OCR automaticamente e repete a mesma pesquisa.
    """

    resultados, diagnostico = (
        pesquisar_processos_pdf_anvisa_sem_ocr(
            caminho_pdf=caminho_pdf,
            documento=documento,
        )
    )

    if (
        diagnostico.get("status_leitura")
        != "SEM_TEXTO_EXTRAIVEL"
    ):
        diagnostico["ocr_aplicado"] = False
        return resultados, diagnostico

    try:
        caminho_ocr, diagnostico_ocr = (
            executar_ocr_pdf_anvisa(
                caminho_pdf=caminho_pdf,
                documento=documento,
            )
        )

        resultados_ocr, leitura_ocr = (
            pesquisar_processos_pdf_anvisa_sem_ocr(
                caminho_pdf=caminho_ocr,
                documento=documento,
            )
        )

        leitura_ocr["ocr_aplicado"] = True
        leitura_ocr["ocr_status"] = (
            diagnostico_ocr.get("status")
        )
        leitura_ocr["arquivo_pdf_original"] = str(
            caminho_pdf
        )
        leitura_ocr["arquivo_pdf_ocr"] = str(
            caminho_ocr
        )
        leitura_ocr["arquivo_log_ocr"] = (
            diagnostico_ocr.get("arquivo_log")
        )

        if (
            leitura_ocr.get("status_leitura")
            == "TEXTO_EXTRAIDO"
        ):
            leitura_ocr["status_leitura"] = (
                "TEXTO_EXTRAIDO_OCR"
            )

        for item in resultados_ocr:
            item["arquivo_pdf_original"] = str(
                caminho_pdf
            )
            item["arquivo_pdf"] = str(
                caminho_ocr
            )
            item["origem_texto"] = "OCR"

        documento["arquivo_pdf_ocr"] = str(
            caminho_ocr
        )

        return resultados_ocr, leitura_ocr

    except Exception as erro:
        diagnostico["ocr_aplicado"] = True
        diagnostico["ocr_status"] = "ERRO"
        diagnostico["ocr_erro"] = str(erro)
        diagnostico["status_leitura"] = (
            "SEM_TEXTO_EXTRAIVEL"
        )

        return resultados, diagnostico


def salvar_resultados_anvisa(
    documentos: list[dict],
    resultados: list[dict],
    erros: list[dict],
) -> dict:
    campos = [
        "fonte",
        "processo",
        "tipo_match",
        "titulo",
        "pagina_pdf",
        "valor_encontrado",
        "trecho",
        "url_item",
        "url_pdf",
        "arquivo_pdf",
        "chave_resultado",
    ]

    with CAMINHO_ANVISA_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=campos,
            delimiter=";",
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(
            resultados
        )

    resumo_por_processo = []

    for processo in PROCESSOS_PESQUISA:
        encontrados = [
            item
            for item in resultados
            if item.get("processo")
            == processo
        ]

        resumo_por_processo.append({
            "processo": processo,
            "total_resultados": len(
                encontrados
            ),
            "status": (
                "ENCONTRADO"
                if encontrados
                else "NAO_ENCONTRADO"
            ),
        })

    resumo = {
        "gerado_em": agora_iso(),
        "fontes": list(
            ANVISA_FONTES.keys()
        ),
        "total_documentos": len(
            documentos
        ),
        "documentos_com_texto": sum(
            1
            for item in documentos
            if (
                item.get("diagnostico_pdf", {})
                .get("status_leitura")
                in {
                    "TEXTO_EXTRAIDO",
                    "TEXTO_EXTRAIDO_OCR",
                }
            )
        ),
        "documentos_sem_texto_extraivel": sum(
            1
            for item in documentos
            if (
                item.get("diagnostico_pdf", {})
                .get("status_leitura")
                == "SEM_TEXTO_EXTRAIVEL"
            )
        ),
        "documentos_processados_por_ocr": sum(
            1
            for item in documentos
            if (
                item.get("diagnostico_pdf", {})
                .get("status_leitura")
                == "TEXTO_EXTRAIDO_OCR"
            )
        ),
        "documentos_com_erro_ocr": sum(
            1
            for item in documentos
            if (
                item.get("diagnostico_pdf", {})
                .get("ocr_status")
                == "ERRO"
            )
        ),
        "total_erros": len(erros),
        "total_resultados": len(
            resultados
        ),
        "processos": resumo_por_processo,
    }

    payload = {
        "resumo": resumo,
        "documentos": documentos,
        "erros": erros,
        "resultados": resultados,
    }

    salvar_json(
        CAMINHO_ANVISA_JSON,
        payload,
    )

    linhas = [
        "=" * 80,
        "PESQUISA DE PROCESSOS — ANVISA/DICOL — 2026",
        "=" * 80,
        f"Documentos analisados: {resumo['total_documentos']}",
        (
            "Documentos com texto: "
            f"{resumo['documentos_com_texto']}"
        ),
        (
            "Documentos processados por OCR: "
            f"{resumo['documentos_processados_por_ocr']}"
        ),
        (
            "Documentos sem texto extraível após OCR: "
            f"{resumo['documentos_sem_texto_extraivel']}"
        ),
        (
            "Documentos com erro de OCR: "
            f"{resumo['documentos_com_erro_ocr']}"
        ),
        f"Erros: {resumo['total_erros']}",
        f"Resultados: {resumo['total_resultados']}",
        "-" * 80,
    ]

    for item in resumo_por_processo:
        linhas.append(
            f"{item['processo']} | "
            f"{item['status']} | "
            f"resultados={item['total_resultados']}"
        )

    linhas.extend([
        "-" * 80,
        f"CSV: {CAMINHO_ANVISA_CSV}",
        f"JSON: {CAMINHO_ANVISA_JSON}",
        "=" * 80,
    ])

    CAMINHO_ANVISA_TXT.write_text(
        "\n".join(linhas),
        encoding="utf-8",
    )

    return resumo


def pesquisar_processos_anvisa_dicol(
    *,
    forcar_download: bool,
) -> tuple[list[dict], dict]:
    print("=" * 80)
    print(
        "FASE 3 — PAUTAS E ATAS DA DICOL/ANVISA"
    )
    print("=" * 80)

    sessao = criar_sessao_http_anvisa()
    documentos: list[dict] = []
    resultados: list[dict] = []
    erros: list[dict] = []

    try:
        for nome_fonte, url_raiz in (
            ANVISA_FONTES.items()
        ):
            try:
                documentos_fonte = (
                    descobrir_pdfs_fonte_anvisa(
                        sessao=sessao,
                        nome_fonte=nome_fonte,
                        url_raiz=url_raiz,
                    )
                )
                documentos.extend(
                    documentos_fonte
                )
            except Exception as erro:
                erros.append({
                    "fonte": nome_fonte,
                    "etapa": (
                        "DESCOBERTA_DOCUMENTOS"
                    ),
                    "erro": str(erro),
                })

        vistos: set[str] = set()
        documentos_unicos = []

        for documento in documentos:
            url_pdf = str(
                documento.get("url_pdf")
                or ""
            )

            if (
                not url_pdf
                or url_pdf in vistos
            ):
                continue

            vistos.add(url_pdf)
            documentos_unicos.append(
                documento
            )

        documentos = documentos_unicos

        for indice, documento in enumerate(
            documentos,
            start=1,
        ):
            print(
                f"[ANVISA] PDF "
                f"{indice}/{len(documentos)} | "
                f"{documento.get('fonte')} | "
                f"{documento.get('titulo')}"
            )

            try:
                caminho_pdf = baixar_pdf_anvisa(
                    sessao=sessao,
                    documento=documento,
                    forcar_download=(
                        forcar_download
                    ),
                )

                documento["_forcar_ocr"] = (
                    forcar_download
                )

                resultados_pdf, diagnostico = (
                    pesquisar_processos_pdf_anvisa(
                        caminho_pdf=caminho_pdf,
                        documento=documento,
                    )
                )

                documento.pop(
                    "_forcar_ocr",
                    None,
                )

                documento["diagnostico_pdf"] = (
                    diagnostico
                )
                documento["total_resultados"] = (
                    len(resultados_pdf)
                )
                resultados.extend(
                    resultados_pdf
                )

            except Exception as erro:
                documento["diagnostico_pdf"] = {
                    "status_leitura": "ERRO",
                    "erro": str(erro),
                }

                erros.append({
                    "fonte": documento.get(
                        "fonte"
                    ),
                    "titulo": documento.get(
                        "titulo"
                    ),
                    "url_pdf": documento.get(
                        "url_pdf"
                    ),
                    "etapa": (
                        "DOWNLOAD_OU_LEITURA_PDF"
                    ),
                    "erro": str(erro),
                })

    finally:
        try:
            sessao.close()
        except Exception:
            pass

    resultados.sort(
        key=lambda item: (
            item.get("fonte") or "",
            item.get("processo") or "",
            item.get("titulo") or "",
            int(
                item.get("pagina_pdf")
                or 0
            ),
        )
    )

    resumo = salvar_resultados_anvisa(
        documentos=documentos,
        resultados=resultados,
        erros=erros,
    )

    salvar_json(
        CAMINHO_ANVISA_MANIFESTO,
        {
            "gerado_em": agora_iso(),
            "fontes": ANVISA_FONTES,
            "resumo": resumo,
            "documentos": documentos,
            "erros": erros,
        },
    )

    print("=" * 80)
    print(
        "PESQUISA ANVISA/DICOL CONCLUÍDA"
    )
    print("=" * 80)
    print(
        f"PDFs analisados: "
        f"{resumo['total_documentos']}"
    )
    print(
        "PDFs processados por OCR: "
        f"{resumo['documentos_processados_por_ocr']}"
    )
    print(
        "PDFs sem texto após OCR: "
        f"{resumo['documentos_sem_texto_extraivel']}"
    )
    print(
        "PDFs com erro de OCR: "
        f"{resumo['documentos_com_erro_ocr']}"
    )
    print(
        f"Erros: {resumo['total_erros']}"
    )
    print(
        f"Resultados encontrados: "
        f"{resumo['total_resultados']}"
    )
    print(f"CSV: {CAMINHO_ANVISA_CSV}")
    print(f"JSON: {CAMINHO_ANVISA_JSON}")
    print("=" * 80)

    return resultados, resumo


def simplificar_resultado_dou(
    item: dict,
) -> dict:
    return {
        "fonte": "DOU_INLABS",
        "processo": (
            item.get("processo")
            or item.get(
                "processo_formatado"
            )
            or item.get(
                "processo_normalizado"
            )
        ),
        "tipo_match": (
            item.get("tipo_match")
            or "EXATO"
        ),
        "data": (
            item.get("data_publicacao")
            or item.get("data")
            or ""
        ),
        "titulo": (
            item.get("titulo")
            or item.get("ementa")
            or ""
        ),
        "pagina": (
            item.get("pagina")
            or ""
        ),
        "trecho": (
            item.get("trecho")
            or item.get("contexto")
            or ""
        ),
        "url": (
            item.get("url")
            or item.get("link")
            or ""
        ),
        "arquivo": (
            item.get("arquivo_xml")
            or ""
        ),
    }


def simplificar_resultado_anvisa(
    item: dict,
) -> dict:
    return {
        "fonte": item.get(
            "fonte"
        ),
        "processo": item.get(
            "processo"
        ),
        "tipo_match": item.get(
            "tipo_match"
        ),
        "data": "",
        "titulo": item.get(
            "titulo"
        ),
        "pagina": item.get(
            "pagina_pdf"
        ),
        "trecho": item.get(
            "trecho"
        ),
        "url": item.get(
            "url_pdf"
        ),
        "arquivo": item.get(
            "arquivo_pdf"
        ),
    }


def salvar_consolidado_todas_fontes(
    resultados_dou: list[dict],
    resultados_anvisa: list[dict],
    resumo_dou: dict,
    resumo_anvisa: dict,
) -> None:
    consolidados = [
        simplificar_resultado_dou(
            item
        )
        for item in resultados_dou
    ]

    consolidados.extend(
        simplificar_resultado_anvisa(
            item
        )
        for item in resultados_anvisa
    )

    campos = [
        "fonte",
        "processo",
        "tipo_match",
        "data",
        "titulo",
        "pagina",
        "trecho",
        "url",
        "arquivo",
    ]

    with CAMINHO_TODAS_FONTES_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=campos,
            delimiter=";",
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(
            consolidados
        )

    resumo = {
        "gerado_em": agora_iso(),
        "total_resultados": len(
            consolidados
        ),
        "resultados_dou": len(
            resultados_dou
        ),
        "resultados_anvisa": len(
            resultados_anvisa
        ),
        "resumo_dou": resumo_dou,
        "resumo_anvisa": resumo_anvisa,
    }

    salvar_json(
        CAMINHO_TODAS_FONTES_JSON,
        {
            "resumo": resumo,
            "resultados": consolidados,
        },
    )

    linhas = [
        "=" * 80,
        "PESQUISA DE PROCESSOS — TODAS AS FONTES",
        "=" * 80,
        (
            "Resultados DOU/INLABS: "
            f"{len(resultados_dou)}"
        ),
        (
            "Resultados Anvisa/Dicol: "
            f"{len(resultados_anvisa)}"
        ),
        (
            "Total consolidado: "
            f"{len(consolidados)}"
        ),
        "-" * 80,
        f"CSV: {CAMINHO_TODAS_FONTES_CSV}",
        f"JSON: {CAMINHO_TODAS_FONTES_JSON}",
        "=" * 80,
    ]

    CAMINHO_TODAS_FONTES_TXT.write_text(
        "\n".join(linhas),
        encoding="utf-8",
    )


# ============================================================
# CONSOLIDAÇÃO
# ============================================================

def carregar_resultados_consolidados(
    datas: list[datetime.date],
) -> list[dict]:
    resultados: list[dict] = []
    chaves_vistas: set[str] = set()

    for data_execucao in datas:
        payload = carregar_json_seguro(
            caminho_resultado_data(data_execucao),
            padrao=None,
        )

        if not payload_resultado_diario_valido(payload):
            continue

        for item in payload.get("resultados", []):
            if not isinstance(item, dict):
                continue

            chave = str(
                item.get("chave_resultado")
                or (
                    f"{item.get('processo_normalizado')}|"
                    f"{item.get('id_publicacao')}|"
                    f"{item.get('data_publicacao')}"
                )
            )

            if chave in chaves_vistas:
                continue

            chaves_vistas.add(chave)
            resultados.append(item)

    resultados.sort(
        key=lambda item: (
            item.get("data_publicacao") or "",
            item.get("processo") or "",
            item.get("orgao") or "",
            item.get("titulo") or "",
        )
    )

    return resultados


def montar_resumo_progresso(
    progresso: dict,
    datas: list[datetime.date],
) -> dict:
    sucesso = 0
    erro_coleta = 0
    erro_processamento = 0
    pendente = 0
    total_registros = 0
    total_resultados = 0

    for data_execucao in datas:
        data_txt = data_execucao.isoformat()
        dados = progresso.get("datas", {}).get(
            data_txt,
            {},
        )

        if resultado_diario_valido(data_execucao):
            sucesso += 1
            total_registros += int(
                dados.get("total_registros_base") or 0
            )
            total_resultados += int(
                dados.get("total_resultados") or 0
            )
        elif dados.get("status") == STATUS_ERRO_COLETA:
            erro_coleta += 1
        elif dados.get("status") == "ERRO_PROCESSAMENTO":
            erro_processamento += 1
        else:
            pendente += 1

    return {
        "total_datas": len(datas),
        "datas_validas": sucesso,
        "datas_erro_coleta": erro_coleta,
        "datas_erro_processamento": erro_processamento,
        "datas_pendentes": pendente,
        "total_registros_base": total_registros,
        "total_resultados": total_resultados,
    }


def carregar_resumo_download_local_reutilizavel(
    data_execucao: datetime.date,
) -> dict | None:
    """
    Reutiliza a validação de coleta existente sem novo acesso ao INLABS.

    Para COLETA_OK, confirma que ao menos um ZIP local ainda contém XML.
    Para SEM_PUBLICACOES_CONFIRMADO, a validação oficial já salva é suficiente.
    """

    resumo = carregar_json_seguro(
        caminho_resumo_inlabs(data_execucao),
        padrao=None,
    )

    if not isinstance(resumo, dict):
        return None

    status = resumo.get("status")

    if status == STATUS_SEM_PUBLICACOES:
        reutilizado = dict(resumo)
        reutilizado["origem_execucao"] = "RESUMO_LOCAL_REUTILIZADO"
        return reutilizado

    if status != STATUS_COLETA_OK:
        return None

    total_zips_validos = 0

    for secao in TIPOS_DOU:
        classificacao, _ = inspecionar_zip_local(
            caminho_zip(data_execucao, secao)
        )

        if classificacao == "ZIP_VALIDO":
            total_zips_validos += 1

    if total_zips_validos < 1:
        return None

    reutilizado = dict(resumo)
    reutilizado["origem_execucao"] = "RESUMO_E_ZIPS_LOCAIS_REUTILIZADOS"
    reutilizado["total_zips_validos_confirmados_localmente"] = (
        total_zips_validos
    )
    return reutilizado


# ============================================================
# EXECUÇÃO
# ============================================================

def executar(args: argparse.Namespace) -> dict:
    global PROCESSOS_PESQUISA

    # A planilha é sempre relida. Portanto, processos incluídos ou excluídos
    # passam a valer imediatamente para o DOU anual e para a Anvisa anual.
    #
    # Mantemos também uma variável local imutável durante toda a execução.
    # Isso evita que a geração final dos relatórios dependa exclusivamente
    # do estado da variável global usada pelas funções auxiliares.
    processos_execucao = carregar_processos_operacionais()
    PROCESSOS_PESQUISA = processos_execucao

    data_inicio = args.inicio
    data_fim = args.fim or resolver_data_fim_padrao()

    validar_periodo(data_inicio, data_fim)

    datas_solicitadas = gerar_datas(
        data_inicio,
        data_fim,
    )

    datas_fora_cobertura = [
        data
        for data in datas_solicitadas
        if data < DATA_INICIO_COBERTURA_INLABS
    ]

    datas_cobertas = [
        data
        for data in datas_solicitadas
        if data >= DATA_INICIO_COBERTURA_INLABS
    ]

    if args.limite_datas is not None:
        if args.limite_datas < 1:
            raise ValueError(
                "--limite-datas deve ser maior que zero."
            )
        datas_cobertas = datas_cobertas[:args.limite_datas]

    progresso = carregar_ou_inicializar_progresso(
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    progresso["processos"] = list(processos_execucao)
    progresso["fonte_processos"] = str(CAMINHO_PALAVRAS_CHAVE)
    progresso["aba_processos"] = "PROCESSOS"
    progresso["coluna_processos"] = "PROCESSO"

    for data_execucao in datas_fora_cobertura:
        progresso.setdefault("datas", {})[
            data_execucao.isoformat()
        ] = {
            "status": STATUS_FORA_COBERTURA,
            "mensagem": (
                "Data anterior ao início confirmado da "
                "cobertura INLABS em 2026-03-23."
            ),
            "atualizado_em": agora_iso(),
        }

    # Toda a base anual será pesquisada novamente, mas downloads válidos
    # e validações de ausência já existentes são reutilizados.
    resumos_locais: dict[str, dict] = {}
    datas_download: list[datetime.date] = []

    for data_execucao in datas_cobertas:
        resumo_local = None

        if not args.forcar_download:
            resumo_local = carregar_resumo_download_local_reutilizavel(
                data_execucao
            )

        if resumo_local is not None:
            resumos_locais[data_execucao.isoformat()] = resumo_local
        else:
            datas_download.append(data_execucao)

    salvar_json(CAMINHO_PROGRESSO, progresso)

    print("=" * 80)
    print("PESQUISA DOU 2026 — ANO INTEIRO")
    print("=" * 80)
    print(
        "Cobertura confirmada: "
        f"{DATA_INICIO_COBERTURA_INLABS.isoformat()} "
        f"a {data_fim.isoformat()}"
    )
    print(f"Processos pesquisados: {len(processos_execucao)}")
    print(f"Datas fora da cobertura: {len(datas_fora_cobertura)}")
    print(f"Datas reutilizadas localmente: {len(resumos_locais)}")
    print(f"Datas que exigem download/validação: {len(datas_download)}")
    print(
        "Regra: todos os processos atuais da planilha serão pesquisados "
        "novamente em todo o acervo anual disponível."
    )
    print("=" * 80)

    manifesto_download = {
        "modo": "SESSAO_UNICA_INLABS",
        "inicio": agora_iso(),
        "fim": agora_iso(),
        "total_logins": 0,
        "datas": {},
        "mensagem": "Nenhuma data precisou de novo download.",
    }

    if datas_download:
        try:
            manifesto_download = executar_download_em_sessao_unica(
                datas=datas_download,
                progresso=progresso,
                reusar_zips_validos=not args.forcar_download,
                pausa_entre_datas=args.pausa_entre_datas,
                max_tentativas_login=args.max_tentativas_login,
            )
        except Exception as erro:
            manifesto_download = {
                "modo": "SESSAO_UNICA_INLABS",
                "inicio": agora_iso(),
                "fim": agora_iso(),
                "total_logins": 0,
                "interrompido": True,
                "motivo_interrupcao": (
                    "Não foi possível obter a sessão inicial do INLABS."
                ),
                "erro_login": str(erro),
                "datas": {},
            }
            salvar_json(CAMINHO_MANIFESTO, manifesto_download)

            print("=" * 80)
            print("DOWNLOADS ANUAIS NÃO CONCLUÍDOS")
            print("=" * 80)
            print(f"Erro: {erro}")
            print(
                "As datas já existentes localmente continuarão sendo "
                "pesquisadas e os resultados anteriores serão preservados."
            )
            print("=" * 80)
    else:
        salvar_json(CAMINHO_MANIFESTO, manifesto_download)

    # Une as datas reaproveitadas com as datas obtidas nesta execução.
    manifesto_processamento = {
        "modo": "PROCESSAMENTO_ANUAL_LOCAL",
        "inicio": agora_iso(),
        "fim": None,
        "datas": {
            **resumos_locais,
            **(manifesto_download.get("datas", {}) or {}),
        },
    }

    datas_processamento = [
        data_execucao
        for data_execucao in datas_cobertas
        if data_execucao.isoformat()
        in manifesto_processamento["datas"]
    ]

    executar_processamento_local(
        datas=datas_processamento,
        manifesto=manifesto_processamento,
        progresso=progresso,
    )
    manifesto_processamento["fim"] = agora_iso()

    datas_consolidacao = gerar_datas(
        DATA_INICIO_COBERTURA_INLABS,
        resolver_data_fim_padrao(),
    )

    resultados_consolidados = carregar_resultados_consolidados(
        datas_consolidacao
    )

    resumo = montar_resumo_progresso(
        progresso=progresso,
        datas=datas_consolidacao,
    )

    arquivos = salvar_relatorios_pesquisa_processos(
        pasta_saida=PASTA_SAIDA,
        resultados=resultados_consolidados,
        data_inicio=DATA_INICIO_COBERTURA_INLABS,
        data_fim=resolver_data_fim_padrao(),
        processos=processos_execucao,
        nome_base="resultado_processos_2026",
        metadados_execucao={
            "modo_coleta": "SESSAO_UNICA_INLABS",
            "modo_pesquisa": "REPROCESSAMENTO_TEXTUAL_ANUAL",
            "fonte_processos": str(CAMINHO_PALAVRAS_CHAVE),
            "aba_processos": "PROCESSOS",
            "coluna_processos": "PROCESSO",
            "cobertura_inlabs_inicio": (
                DATA_INICIO_COBERTURA_INLABS.isoformat()
            ),
            "manifesto_download": str(CAMINHO_MANIFESTO),
            "progresso": resumo,
        },
    )

    progresso["resumo"] = resumo
    progresso["atualizado_em"] = agora_iso()
    salvar_json(CAMINHO_PROGRESSO, progresso)

    resultados_anvisa: list[dict] = []
    resumo_anvisa = {
        "status": "IGNORADO",
        "total_documentos": 0,
        "total_resultados": 0,
        "total_erros": 0,
    }

    if not args.ignorar_anvisa:
        try:
            resultados_anvisa, resumo_anvisa = (
                pesquisar_processos_anvisa_dicol(
                    forcar_download=args.forcar_anvisa,
                )
            )
            resumo_anvisa["status"] = (
                "SUCESSO"
                if int(resumo_anvisa.get("total_erros") or 0) == 0
                else "CONCLUIDO_COM_PENDENCIAS"
            )
        except Exception as erro:
            resumo_anvisa = {
                "status": "ERRO",
                "erro": str(erro),
                "total_documentos": 0,
                "total_resultados": 0,
                "total_erros": 1,
            }

            print("=" * 80)
            print("ERRO NA PESQUISA ANVISA/DICOL")
            print("=" * 80)
            print(f"Erro: {erro}")
            print("Os resultados do DOU foram preservados.")
            print("=" * 80)

    salvar_consolidado_todas_fontes(
        resultados_dou=resultados_consolidados,
        resultados_anvisa=resultados_anvisa,
        resumo_dou=resumo,
        resumo_anvisa=resumo_anvisa,
    )

    total_pendencias = (
        int(resumo.get("datas_erro_coleta") or 0)
        + int(resumo.get("datas_erro_processamento") or 0)
        + int(resumo.get("datas_pendentes") or 0)
        + int(resumo_anvisa.get("total_erros") or 0)
        + int(resumo_anvisa.get("documentos_sem_texto_extraivel") or 0)
    )

    status_final = (
        "SUCESSO"
        if total_pendencias == 0
        else "CONCLUIDO_COM_PENDENCIAS"
    )

    resultado_final = {
        "status": status_final,
        "gerado_em": agora_iso(),
        "ano": 2026,
        "fonte_processos": str(CAMINHO_PALAVRAS_CHAVE),
        "aba_processos": "PROCESSOS",
        "coluna_processos": "PROCESSO",
        "processos": list(processos_execucao),
        "total_processos": len(processos_execucao),
        "dou": resumo,
        "anvisa": resumo_anvisa,
        "resultados_dou": len(resultados_consolidados),
        "resultados_anvisa": len(resultados_anvisa),
        "resultados_todas_fontes": (
            len(resultados_consolidados) + len(resultados_anvisa)
        ),
        "pendencias_tecnicas": total_pendencias,
        "arquivos": {
            "dou_csv": arquivos["csv"],
            "dou_json": arquivos["json"],
            "dou_txt": arquivos["txt"],
            "anvisa_json": str(CAMINHO_ANVISA_JSON),
            "consolidado_json": str(CAMINHO_TODAS_FONTES_JSON),
        },
    }

    print("=" * 80)
    print("PESQUISA CONSOLIDADA ATUALIZADA")
    print("=" * 80)
    print(f"Status: {status_final}")
    print(f"Processos da planilha: {len(processos_execucao)}")
    print(f"Datas válidas: {resumo['datas_validas']}")
    print(
        "Datas com erro de coleta: "
        f"{resumo['datas_erro_coleta']}"
    )
    print(
        "Datas com erro de processamento: "
        f"{resumo['datas_erro_processamento']}"
    )
    print(f"Datas pendentes: {resumo['datas_pendentes']}")
    print(f"Resultados DOU: {len(resultados_consolidados)}")
    print(f"Resultados Anvisa/Dicol: {len(resultados_anvisa)}")
    print(
        "Resultados em todas as fontes: "
        f"{len(resultados_consolidados) + len(resultados_anvisa)}"
    )
    print(f"Pendências técnicas: {total_pendencias}")
    print("-" * 80)
    print(f"CSV: {arquivos['csv']}")
    print(f"JSON: {arquivos['json']}")
    print(f"TXT: {arquivos['txt']}")
    print(f"Progresso: {CAMINHO_PROGRESSO}")
    print(f"Manifesto DOU: {CAMINHO_MANIFESTO}")
    print(f"Resultado Anvisa: {CAMINHO_ANVISA_JSON}")
    print(
        "Consolidado todas as fontes: "
        f"{CAMINHO_TODAS_FONTES_JSON}"
    )
    print("=" * 80)

    return resultado_final


def executar_monitoramento_processos_anual() -> dict:
    """
    Entrada reutilizável chamada pelo runner oficial do DOU.

    Sempre pesquisa a lista atual da planilha em todo o acervo disponível
    de 2026, reutilizando ZIPs, PDFs e arquivos de OCR existentes.
    """

    args = argparse.Namespace(
        inicio=DATA_INICIO_COBERTURA_INLABS,
        fim=resolver_data_fim_padrao(),
        limite_datas=None,
        reprocessar=True,
        forcar_download=False,
        pausa_entre_datas=PAUSA_ENTRE_DATAS_PADRAO,
        max_tentativas_login=MAX_TENTATIVAS_LOGIN_PADRAO,
        ignorar_anvisa=False,
        forcar_anvisa=False,
    )

    return executar(args)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pesquisa processos no DOU e nos PDFs de "
            "atas e pautas da Dicol/Anvisa."
        )
    )

    parser.add_argument(
        "--inicio",
        type=converter_data,
        default=DATA_INICIO_COBERTURA_INLABS,
        help=(
            "Data inicial. Padrão: 2026-03-23, início "
            "confirmado da cobertura INLABS."
        ),
    )

    parser.add_argument(
        "--fim",
        type=converter_data,
        default=None,
        help="Data final. Padrão: hoje.",
    )

    parser.add_argument(
        "--limite-datas",
        type=int,
        default=None,
        help=(
            "Limita a quantidade de datas para teste."
        ),
    )

    parser.add_argument(
        "--reprocessar-datas",
        "--reprocessar",
        dest="reprocessar",
        action="store_true",
        help=(
            "Mantido por compatibilidade. A pesquisa textual anual "
            "já é refeita automaticamente em todas as execuções."
        ),
    )

    parser.add_argument(
        "--forcar-base",
        "--forcar-download",
        dest="forcar_download",
        action="store_true",
        help=(
            "Baixa novamente até os ZIPs locais válidos "
            "e reconstrói a base da pesquisa."
        ),
    )

    parser.add_argument(
        "--pausa-entre-datas",
        type=float,
        default=PAUSA_ENTRE_DATAS_PADRAO,
        help=(
            "Pausa em segundos entre datas. Padrão: 1."
        ),
    )

    parser.add_argument(
        "--max-tentativas-login",
        type=int,
        default=MAX_TENTATIVAS_LOGIN_PADRAO,
        help=(
            "Tentativas para obter a sessão inicial "
            "do INLABS. Padrão: 6."
        ),
    )

    parser.add_argument(
        "--ignorar-anvisa",
        action="store_true",
        help=(
            "Não acessa as páginas de atas e pautas "
            "da Dicol/Anvisa."
        ),
    )

    parser.add_argument(
        "--forcar-anvisa",
        action="store_true",
        help=(
            "Baixa novamente os PDFs da Anvisa, "
            "mesmo quando já existirem localmente."
        ),
    )

    return parser


def validar_argumentos(
    args: argparse.Namespace,
) -> None:
    if args.limite_datas is not None:
        if args.limite_datas < 1:
            raise ValueError(
                "--limite-datas deve ser maior que zero."
            )

    if args.pausa_entre_datas < 0:
        raise ValueError(
            "--pausa-entre-datas não pode ser negativa."
        )

    if args.max_tentativas_login < 1:
        raise ValueError(
            "--max-tentativas-login deve ser "
            "maior que zero."
        )


def main() -> None:
    parser = montar_parser()
    args = parser.parse_args()
    validar_argumentos(args)
    executar(args)


if __name__ == "__main__":
    main()
