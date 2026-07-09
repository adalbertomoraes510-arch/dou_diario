# ============================================================
# RUNNER — Validar Contrato de Publicação Multi-Fonte com DOU
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Validar se a base atual do DOU consegue ser convertida para o
# contrato padrão PublicacaoPadrao.
#
# Este runner NÃO altera o fluxo oficial.
# Este runner NÃO executa busca no DOU.
# Este runner NÃO altera match, auditoria ou relatório.
# ============================================================

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.models.publicacao_padrao import (
    normalizar_publicacao_dou,
    obter_documentacao_contrato_publicacao,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# None = usa a base mais recente encontrada em backend/data/dou/base
DATA_PUBLICACAO: Optional[date] = None

# None = valida todas as publicações
LIMITE_PUBLICACOES: Optional[int] = None

PASTA_BASE_DOU = Path("backend/data/dou/base")

PASTA_SAIDA = Path("backend/data/dou/mapeamentos/contrato_publicacao")


# ============================================================
# UTILITÁRIOS
# ============================================================

def imprimir_titulo(texto: str) -> None:
    print("=" * 80)
    print(texto)
    print("=" * 80)


def garantir_pasta_saida() -> None:
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)


def extrair_data_do_nome_arquivo(caminho: Path) -> Optional[str]:
    match = re.search(r"base_publicacoes_(\d{4}-\d{2}-\d{2})\.json$", caminho.name)
    if not match:
        return None

    return match.group(1)


def resolver_arquivo_base() -> Path:
    """
    Resolve qual arquivo de base DOU será validado.

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

    arquivos_com_data = []

    for arquivo in arquivos:
        data_arquivo = extrair_data_do_nome_arquivo(arquivo)

        if data_arquivo:
            arquivos_com_data.append((data_arquivo, arquivo))

    if not arquivos_com_data:
        raise FileNotFoundError(
            f"Nenhum arquivo base_publicacoes_YYYY-MM-DD.json válido encontrado em: {PASTA_BASE_DOU}"
        )

    arquivos_com_data.sort(key=lambda item: item[0])

    return arquivos_com_data[-1][1]


def carregar_json(caminho: Path) -> Any:
    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def salvar_json(caminho: Path, dados: Any) -> None:
    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def salvar_txt(caminho: Path, texto: str) -> None:
    with caminho.open("w", encoding="utf-8") as arquivo:
        arquivo.write(texto)


def extrair_lista_publicacoes(dados: Any) -> List[Dict[str, Any]]:
    """
    Extrai a lista de publicações de diferentes formatos possíveis.

    Aceita:
    - lista direta;
    - dict com chave publicacoes;
    - dict com chave registros;
    - dict com chave dados;
    - dict com chave base_publicacoes.
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


def montar_relatorio_txt(resultado: Dict[str, Any]) -> str:
    linhas = []

    linhas.append("=" * 80)
    linhas.append("VALIDAÇÃO DO CONTRATO DE PUBLICAÇÃO MULTI-FONTE COM BASE DOU")
    linhas.append("=" * 80)
    linhas.append("")
    linhas.append(f"Data da validação: {resultado.get('data_validacao')}")
    linhas.append(f"Arquivo origem: {resultado.get('arquivo_origem')}")
    linhas.append(f"Data DOU detectada: {resultado.get('data_publicacao')}")
    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("RESUMO")
    linhas.append("-" * 80)
    linhas.append(f"Total publicações origem: {resultado.get('total_origem')}")
    linhas.append(f"Total validadas: {resultado.get('total_validadas')}")
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
        linhas.append("ERROS")
        linhas.append("-" * 80)

        for erro in resultado.get("erros", []):
            linhas.append("")
            linhas.append(f"Índice: {erro.get('indice')}")
            linhas.append(f"Erro: {erro.get('erro')}")

    linhas.append("")
    linhas.append("=" * 80)
    linhas.append("FIM DA VALIDAÇÃO")
    linhas.append("=" * 80)

    return "\n".join(linhas)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar_validacao_contrato_dou() -> Dict[str, Any]:
    garantir_pasta_saida()

    arquivo_base = resolver_arquivo_base()
    data_publicacao = extrair_data_do_nome_arquivo(arquivo_base) or ""

    dados_origem = carregar_json(arquivo_base)
    publicacoes_origem = extrair_lista_publicacoes(dados_origem)

    if LIMITE_PUBLICACOES is not None:
        publicacoes_origem = publicacoes_origem[:LIMITE_PUBLICACOES]

    publicacoes_convertidas: List[Dict[str, Any]] = []
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

            publicacoes_convertidas.append(publicacao_dict)

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
                    "erro": str(erro),
                    "tipo": type(erro).__name__,
                }
            )

    total_origem = len(publicacoes_origem)
    total_validadas = len(publicacoes_convertidas)
    total_erros_tecnicos = len(erros)

    if total_origem == 0:
        status_final = "SEM_PUBLICACOES_ORIGEM"
    elif total_erros_tecnicos > 0:
        status_final = "VALIDACAO_COM_ERROS_TECNICOS"
    elif total_invalidas > 0:
        status_final = "CONTRATO_COM_PUBLICACOES_INVALIDAS"
    elif total_incompletas > 0:
        status_final = "CONTRATO_VALIDADO_COM_AVISOS"
    else:
        status_final = "CONTRATO_VALIDADO_COM_SUCESSO"

    resultado = {
        "data_validacao": datetime.now().isoformat(timespec="seconds"),
        "arquivo_origem": str(arquivo_base),
        "data_publicacao": data_publicacao,
        "limite_publicacoes": LIMITE_PUBLICACOES,
        "status_final": status_final,
        "total_origem": total_origem,
        "total_validadas": total_validadas,
        "total_ok": total_ok,
        "total_incompletas": total_incompletas,
        "total_invalidas": total_invalidas,
        "total_erros_tecnicos": total_erros_tecnicos,
        "erros": erros,
        "amostra": publicacoes_convertidas[:5],
        "contrato": obter_documentacao_contrato_publicacao(),
        "publicacoes_convertidas": publicacoes_convertidas,
    }

    sufixo_data = data_publicacao or datetime.now().strftime("%Y-%m-%d")

    caminho_json = (
        PASTA_SAIDA / f"validacao_contrato_publicacao_dou_{sufixo_data}.json"
    )

    caminho_txt = (
        PASTA_SAIDA / f"validacao_contrato_publicacao_dou_{sufixo_data}.txt"
    )

    salvar_json(caminho_json, resultado)
    salvar_txt(caminho_txt, montar_relatorio_txt(resultado))

    resultado["_arquivo_saida_json"] = str(caminho_json)
    resultado["_arquivo_saida_txt"] = str(caminho_txt)

    return resultado


def main() -> None:
    imprimir_titulo("VALIDANDO CONTRATO PUBLICACAO MULTI-FONTE COM BASE DOU")

    try:
        resultado = executar_validacao_contrato_dou()

        print(f"Arquivo origem: {resultado.get('arquivo_origem')}")
        print(f"Data DOU detectada: {resultado.get('data_publicacao')}")
        print(f"Status final: {resultado.get('status_final')}")
        print(f"Total origem: {resultado.get('total_origem')}")
        print(f"Total validadas: {resultado.get('total_validadas')}")
        print(f"Total OK: {resultado.get('total_ok')}")
        print(f"Total incompletas: {resultado.get('total_incompletas')}")
        print(f"Total inválidas: {resultado.get('total_invalidas')}")
        print(f"Total erros técnicos: {resultado.get('total_erros_tecnicos')}")
        print("")
        print(f"JSON: {resultado.get('_arquivo_saida_json')}")
        print(f"TXT:  {resultado.get('_arquivo_saida_txt')}")

        imprimir_titulo("VALIDACAO FINALIZADA")

    except Exception as erro:
        imprimir_titulo("ERRO NA VALIDACAO DO CONTRATO")
        print(f"Tipo: {type(erro).__name__}")
        print(f"Erro: {erro}")
        raise


if __name__ == "__main__":
    main()