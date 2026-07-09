# ============================================================
# RUNNER — Gerar Base Padronizada DOU no Contrato Multi-Fonte
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Ler a base auditável atual do DOU:
#
#   backend/data/dou/base/base_publicacoes_YYYY-MM-DD.json
#
# Converter as publicações para o contrato padrão:
#
#   PublicacaoPadrao
#
# E salvar uma base paralela padronizada em:
#
#   backend/data/publicacoes_padrao/dou/publicacoes_padrao_YYYY-MM-DD.json
#
# Importante:
# - Este runner NÃO altera o fluxo oficial atual do DOU.
# - Este runner NÃO altera match.
# - Este runner NÃO altera curadoria.
# - Este runner NÃO altera relatório.
# - Este runner apenas gera uma base paralela para preparar a arquitetura multi-fonte.
# ============================================================

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.models.publicacao_padrao import normalizar_publicacao_dou


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# None = usa a base mais recente encontrada em backend/data/dou/base
# Exemplo fixo:
# DATA_PUBLICACAO: Optional[date] = date(2026, 5, 14)
DATA_PUBLICACAO: Optional[date] = None

# None = converte todas as publicações
# Exemplo para teste:
# LIMITE_PUBLICACOES: Optional[int] = 50
LIMITE_PUBLICACOES: Optional[int] = None

ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_BASE_DOU = ROOT_DIR / "backend" / "data" / "dou" / "base"

PASTA_SAIDA = (
    ROOT_DIR
    / "backend"
    / "data"
    / "publicacoes_padrao"
    / "dou"
)


# ============================================================
# UTILITÁRIOS
# ============================================================

def imprimir_titulo(texto: str) -> None:
    print("=" * 80)
    print(texto)
    print("=" * 80)


def garantir_pasta_saida() -> None:
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)


def carregar_json(caminho: Path) -> Any:
    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def salvar_json(caminho: Path, dados: Any) -> None:
    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def salvar_txt(caminho: Path, texto: str) -> None:
    with caminho.open("w", encoding="utf-8") as arquivo:
        arquivo.write(texto)


def extrair_data_do_nome_arquivo(caminho: Path) -> Optional[str]:
    match = re.search(
        r"base_publicacoes_(\d{4}-\d{2}-\d{2})\.json$",
        caminho.name,
    )

    if not match:
        return None

    return match.group(1)


def resolver_arquivo_base() -> Path:
    """
    Resolve qual base DOU será usada.

    Se DATA_PUBLICACAO estiver preenchida:
        usa backend/data/dou/base/base_publicacoes_YYYY-MM-DD.json

    Se DATA_PUBLICACAO for None:
        usa o arquivo base_publicacoes_*.json mais recente encontrado.
    """
    if DATA_PUBLICACAO is not None:
        data_str = DATA_PUBLICACAO.strftime("%Y-%m-%d")
        caminho = PASTA_BASE_DOU / f"base_publicacoes_{data_str}.json"

        if not caminho.exists():
            raise FileNotFoundError(
                f"Base DOU não encontrada para a data {data_str}: {caminho}"
            )

        return caminho

    arquivos = sorted(PASTA_BASE_DOU.glob("base_publicacoes_*.json"))

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo base_publicacoes_*.json encontrado em: {PASTA_BASE_DOU}"
        )

    arquivos_com_data: List[tuple[str, Path]] = []

    for arquivo in arquivos:
        data_arquivo = extrair_data_do_nome_arquivo(arquivo)

        if data_arquivo:
            arquivos_com_data.append((data_arquivo, arquivo))

    if not arquivos_com_data:
        raise FileNotFoundError(
            "Nenhum arquivo no padrão base_publicacoes_YYYY-MM-DD.json "
            f"foi encontrado em: {PASTA_BASE_DOU}"
        )

    arquivos_com_data.sort(key=lambda item: item[0])

    return arquivos_com_data[-1][1]


def extrair_lista_publicacoes(dados: Any) -> List[Dict[str, Any]]:
    """
    Extrai a lista de publicações da base DOU.

    Aceita formatos possíveis:
    - lista direta;
    - dict com chave publicacoes;
    - dict com chave registros;
    - dict com chave dados;
    - dict com chave base_publicacoes;
    - dict com chave itens.
    """
    if isinstance(dados, list):
        return [item for item in dados if isinstance(item, dict)]

    if not isinstance(dados, dict):
        raise ValueError(
            f"Formato JSON não suportado. Tipo recebido: {type(dados).__name__}"
        )

    chaves_possiveis = [
        "publicacoes",
        "registros",
        "dados",
        "base_publicacoes",
        "itens",
    ]

    for chave in chaves_possiveis:
        valor = dados.get(chave)

        if isinstance(valor, list):
            return [item for item in valor if isinstance(item, dict)]

    raise ValueError(
        "Não foi possível localizar lista de publicações no JSON. "
        f"Chaves disponíveis: {list(dados.keys())}"
    )


def montar_resumo_txt(resultado: Dict[str, Any]) -> str:
    linhas: List[str] = []

    linhas.append("=" * 80)
    linhas.append("GERAÇÃO DA BASE PADRONIZADA DOU — CONTRATO MULTI-FONTE")
    linhas.append("=" * 80)
    linhas.append("")
    linhas.append(f"Data de geração: {resultado.get('data_geracao')}")
    linhas.append(f"Fonte: {resultado.get('fonte')}")
    linhas.append(f"Data DOU: {resultado.get('data_publicacao')}")
    linhas.append(f"Arquivo origem: {resultado.get('arquivo_origem')}")
    linhas.append(f"Arquivo saída: {resultado.get('arquivo_saida_json')}")
    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("RESUMO")
    linhas.append("-" * 80)
    linhas.append(f"Total origem: {resultado.get('total_origem')}")
    linhas.append(f"Total convertidas: {resultado.get('total_convertidas')}")
    linhas.append(f"Total OK: {resultado.get('total_ok')}")
    linhas.append(f"Total incompletas: {resultado.get('total_incompletas')}")
    linhas.append(f"Total inválidas: {resultado.get('total_invalidas')}")
    linhas.append(f"Total erros técnicos: {resultado.get('total_erros_tecnicos')}")
    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("STATUS FINAL")
    linhas.append("-" * 80)
    linhas.append(str(resultado.get("status_final")))
    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("AMOSTRA")
    linhas.append("-" * 80)

    for item in resultado.get("amostra", []):
        linhas.append("")
        linhas.append(f"ID padrão: {item.get('id_publicacao')}")
        linhas.append(f"Fonte: {item.get('fonte')}")
        linhas.append(f"Data: {item.get('data_publicacao')}")
        linhas.append(f"Título: {item.get('titulo')}")
        linhas.append(f"Órgão: {item.get('orgao')}")
        linhas.append(f"Status normalização: {item.get('status_normalizacao')}")

    if resultado.get("erros"):
        linhas.append("")
        linhas.append("-" * 80)
        linhas.append("ERROS TÉCNICOS")
        linhas.append("-" * 80)

        for erro in resultado.get("erros", []):
            linhas.append("")
            linhas.append(f"Índice: {erro.get('indice')}")
            linhas.append(f"Tipo: {erro.get('tipo')}")
            linhas.append(f"Erro: {erro.get('erro')}")

    linhas.append("")
    linhas.append("=" * 80)
    linhas.append("FIM DA GERAÇÃO")
    linhas.append("=" * 80)

    return "\n".join(linhas)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def gerar_base_publicacoes_padrao_dou() -> Dict[str, Any]:
    garantir_pasta_saida()

    arquivo_base = resolver_arquivo_base()
    data_publicacao = extrair_data_do_nome_arquivo(arquivo_base) or ""

    dados_origem = carregar_json(arquivo_base)
    publicacoes_origem = extrair_lista_publicacoes(dados_origem)

    if LIMITE_PUBLICACOES is not None:
        publicacoes_origem = publicacoes_origem[:LIMITE_PUBLICACOES]

    publicacoes_padrao: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []

    total_ok = 0
    total_incompletas = 0
    total_invalidas = 0

    for indice, publicacao_origem in enumerate(publicacoes_origem, start=1):
        try:
            publicacao_padrao = normalizar_publicacao_dou(
                publicacao_dou=publicacao_origem,
                data_publicacao_padrao=data_publicacao,
                origem_arquivo=str(arquivo_base),
            )

            validacao = publicacao_padrao.validar()
            publicacao_dict = publicacao_padrao.to_dict()
            publicacao_dict["_validacao"] = validacao

            publicacoes_padrao.append(publicacao_dict)

            status = publicacao_padrao.status_normalizacao

            if status == "OK":
                total_ok += 1
            elif status == "INCOMPLETA":
                total_incompletas += 1
            else:
                total_invalidas += 1

        except Exception as erro:
            erros.append(
                {
                    "indice": indice,
                    "tipo": type(erro).__name__,
                    "erro": str(erro),
                }
            )

    total_origem = len(publicacoes_origem)
    total_convertidas = len(publicacoes_padrao)
    total_erros_tecnicos = len(erros)

    if total_origem == 0:
        status_final = "SEM_PUBLICACOES_ORIGEM"
    elif total_erros_tecnicos > 0:
        status_final = "BASE_PADRONIZADA_GERADA_COM_ERROS_TECNICOS"
    elif total_invalidas > 0:
        status_final = "BASE_PADRONIZADA_GERADA_COM_INVALIDAS"
    elif total_incompletas > 0:
        status_final = "BASE_PADRONIZADA_GERADA_COM_AVISOS"
    else:
        status_final = "BASE_PADRONIZADA_GERADA_COM_SUCESSO"

    sufixo_data = data_publicacao or datetime.now().strftime("%Y-%m-%d")

    caminho_json = PASTA_SAIDA / f"publicacoes_padrao_{sufixo_data}.json"
    caminho_txt = PASTA_SAIDA / f"resumo_publicacoes_padrao_{sufixo_data}.txt"

    resultado = {
        "tipo_base": "publicacoes_padrao",
        "fonte": "dou",
        "data_publicacao": data_publicacao,
        "data_geracao": datetime.now().isoformat(timespec="seconds"),
        "arquivo_origem": str(arquivo_base),
        "arquivo_saida_json": str(caminho_json),
        "arquivo_saida_txt": str(caminho_txt),
        "limite_publicacoes": LIMITE_PUBLICACOES,
        "status_final": status_final,
        "total_origem": total_origem,
        "total_convertidas": total_convertidas,
        "total_ok": total_ok,
        "total_incompletas": total_incompletas,
        "total_invalidas": total_invalidas,
        "total_erros_tecnicos": total_erros_tecnicos,
        "erros": erros,
        "amostra": publicacoes_padrao[:5],
        "publicacoes": publicacoes_padrao,
    }

    salvar_json(caminho_json, resultado)
    salvar_txt(caminho_txt, montar_resumo_txt(resultado))

    return resultado


def main() -> None:
    imprimir_titulo("GERANDO BASE PADRONIZADA DOU — CONTRATO MULTI-FONTE")

    try:
        resultado = gerar_base_publicacoes_padrao_dou()

        print(f"Arquivo origem: {resultado.get('arquivo_origem')}")
        print(f"Data DOU detectada: {resultado.get('data_publicacao')}")
        print(f"Status final: {resultado.get('status_final')}")
        print(f"Total origem: {resultado.get('total_origem')}")
        print(f"Total convertidas: {resultado.get('total_convertidas')}")
        print(f"Total OK: {resultado.get('total_ok')}")
        print(f"Total incompletas: {resultado.get('total_incompletas')}")
        print(f"Total inválidas: {resultado.get('total_invalidas')}")
        print(f"Total erros técnicos: {resultado.get('total_erros_tecnicos')}")
        print("")
        print(f"JSON: {resultado.get('arquivo_saida_json')}")
        print(f"TXT:  {resultado.get('arquivo_saida_txt')}")

        imprimir_titulo("BASE PADRONIZADA GERADA")

    except Exception as erro:
        imprimir_titulo("ERRO AO GERAR BASE PADRONIZADA DOU")
        print(f"Tipo: {type(erro).__name__}")
        print(f"Erro: {erro}")
        raise


if __name__ == "__main__":
    main()