# ============================================================
# SERVICE — Curadoria do Boletim Informativo
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Ler publicações da finalidade "informativos" e gerar um
# pré-boletim curado por dia ou período.
#
# Esta camada NÃO executa busca no DOU.
# Esta camada NÃO altera match_service.py.
# Esta camada NÃO altera orquestrador.
# Esta camada NÃO envia e-mail.
#
# Ela apenas lê arquivos já gerados e monta:
# - JSON estruturado do pré-boletim;
# - TXT executivo do pré-boletim;
# - TXT com prompt pronto para IA revisar/redigir.
# ============================================================

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.models.boletim_informativo import (
    BoletimInformativo,
    ItemBoletimInformativo,
    construir_boletim_informativo,
    construir_item_boletim,
    RELACAO_DIRETA_LEROY,
    PRODUTO_COMERCIALIZADO,
    CERTIFICACAO_SEGURANCA_CONFORMIDADE,
    IMPORTACAO_COMERCIO_REGULACAO,
    ORGAO_REGULADOR_RELEVANTE,
    MONITORAMENTO_SETORIAL,
    DESCARTADO_SEM_RELACAO_MATERIAL,
    RELEVANCIA_ALTA,
    RELEVANCIA_MEDIA,
    RELEVANCIA_BAIXA,
    RELEVANCIA_DESCARTADO,
    SECAO_PUBLICACOES_DIRETAS_LEROY,
    SECAO_PRODUTOS_COMERCIALIZADOS,
    SECAO_NORMAS_CERTIFICACOES_SEGURANCA,
    SECAO_IMPORTACAO_COMERCIO_REGULACAO,
    SECAO_ORGAOS_REGULADORES,
    SECAO_MONITORAMENTO_SETORIAL,
    SECAO_ITENS_DESCARTADOS,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

FINALIDADE = "informativos"

PASTA_DATA_DOU = Path("backend/data/dou")

PASTA_RELATORIOS_INFORMATIVOS = (
    PASTA_DATA_DOU / "relatorios" / FINALIDADE
)

PASTA_MATCH_INFORMATIVOS = (
    PASTA_DATA_DOU / "match" / FINALIDADE
)

PASTA_CONSOLIDADOS_PERIODO = (
    PASTA_DATA_DOU / "consolidados_periodo"
)

PASTA_BASE_PUBLICACOES = (
    PASTA_DATA_DOU / "base"
)

PASTA_SAIDA_BOLETINS = (
    PASTA_DATA_DOU / "boletins" / FINALIDADE
)

PASTA_PROMPTS_IA = (
    PASTA_SAIDA_BOLETINS / "prompts_ia"
)


# ============================================================
# VISÃO EXECUTIVA DO BOLETIM
# ============================================================

VISAO_DESTAQUE_EXECUTIVO = "DESTAQUE_EXECUTIVO"
VISAO_POSSIVEL_DESTAQUE_REVISAO = "POSSIVEL_DESTAQUE_REVISAO"
VISAO_MONITORAMENTO = "MONITORAMENTO"
VISAO_DESCARTADO = "DESCARTADO"
VISAO_REVISAO_HUMANA = "REVISAO_HUMANA"


# ============================================================
# VOCABULÁRIOS DE CURADORIA
# ============================================================

TERMOS_LEROY = [
    "leroy",
    "leroy merlin",
    "leroymerlin",
]

TERMOS_CERTIFICACAO_SEGURANCA = [
    "certificação",
    "certificacao",
    "certificado",
    "conformidade",
    "segurança",
    "seguranca",
    "qualidade",
    "ensaio",
    "ensaios",
    "homologação",
    "homologacao",
    "acreditação",
    "acreditacao",
    "normalização",
    "normalizacao",
    "norma técnica",
    "norma tecnica",
    "regulamento técnico",
    "regulamento tecnico",
    "inmetro",
    "abnt",
]

TERMOS_CERTIFICACAO_AMBIGUOS = [
    "registro",
    "registros",
]

TERMOS_IMPORTACAO_COMERCIO = [
    "importação",
    "importacao",
    "exportação",
    "exportacao",
    "comércio exterior",
    "comercio exterior",
    "licença de importação",
    "licenca de importacao",
    "anuência",
    "anuencia",
    "siscomex",
    "aduaneiro",
    "alfandegário",
    "alfandegario",
    "tributação",
    "tributacao",
    "tarifa",
    "ncm",
    "drawback",
    "antidumping",
]

TERMOS_PRODUTOS_LEROY_FORTES = [
    "ferramenta",
    "ferramentas",
    "furadeira",
    "furadeiras",
    "parafusadeira",
    "parafusadeiras",
    "serra",
    "serras",
    "lixadeira",
    "lixadeiras",
    "esmerilhadeira",
    "esmerilhadeiras",
    "tinta",
    "tintas",
    "verniz",
    "vernizes",
    "solvente",
    "solventes",
    "cimento",
    "argamassa",
    "argamassas",
    "rejunte",
    "rejuntes",
    "piso",
    "pisos",
    "revestimento",
    "revestimentos",
    "porcelanato",
    "porcelanatos",
    "cerâmica",
    "ceramica",
    "cerâmicas",
    "ceramicas",
    "madeira",
    "madeiras",
    "mdf",
    "janela",
    "janelas",
    "vidro",
    "vidros",
    "chuveiro",
    "chuveiros",
    "torneira",
    "torneiras",
    "metais sanitários",
    "metais sanitarios",
    "lâmpada",
    "lampada",
    "lâmpadas",
    "lampadas",
    "led",
    "iluminação",
    "iluminacao",
    "cabo elétrico",
    "cabo eletrico",
    "cabos elétricos",
    "cabos eletricos",
    "fio elétrico",
    "fio eletrico",
    "fios elétricos",
    "fios eletricos",
    "tomada",
    "tomadas",
    "interruptor",
    "interruptores",
    "disjuntor",
    "disjuntores",
    "ar condicionado",
    "condicionador de ar",
    "ventilador",
    "ventiladores",
    "aquecedor",
    "aquecedores",
    "eletrodoméstico",
    "eletrodomestico",
    "eletrodomésticos",
    "eletrodomesticos",
    "móvel",
    "movel",
    "móveis",
    "moveis",
    "decoração",
    "decoracao",
    "jardim",
    "jardinagem",
    "piscina",
    "piscinas",
    "escada",
    "escadas",
    "andaime",
    "andaimes",
    "epi",
    "epis",
    "equipamento de proteção",
    "equipamento de protecao",
    "equipamentos de proteção",
    "equipamentos de protecao",
]

TERMOS_PRODUTOS_AMBIGUOS = [
    "porta",
    "portas",
    "registro",
    "registros",
    "químico",
    "quimico",
    "químicos",
    "quimicos",
]

CONTEXTOS_PORTA_PRODUTO = [
    "porta de madeira",
    "porta de aço",
    "porta de aco",
    "porta corta-fogo",
    "porta corta fogo",
    "porta de correr",
    "porta sanfonada",
    "porta camarão",
    "porta camarao",
    "porta pivotante",
    "porta interna",
    "porta externa",
    "porta pronta",
    "porta balcão",
    "porta balcao",
    "folha de porta",
    "batente",
    "guarnição",
    "guarnicao",
    "fechadura",
    "dobradiça",
    "dobradica",
]

CONTEXTOS_REGISTRO_PRODUTO = [
    "registro hidráulico",
    "registro hidraulico",
    "registro de chuveiro",
    "registro de pressão",
    "registro de pressao",
    "registro de gaveta",
    "registro esfera",
    "registro para banheiro",
    "registro para cozinha",
    "torneira e registro",
    "metais sanitários",
    "metais sanitarios",
]

CONTEXTOS_QUIMICO_PRODUTO = [
    "produto químico",
    "produto quimico",
    "produtos químicos",
    "produtos quimicos",
    "saneante",
    "saneantes",
    "solvente",
    "solventes",
    "tinta",
    "tintas",
    "verniz",
    "vernizes",
    "resina",
    "resinas",
    "cola",
    "colas",
    "adesivo",
    "adesivos",
    "limpador",
    "limpadores",
    "desinfetante",
    "desinfetantes",
]

CONTEXTOS_REGISTRO_ADMINISTRATIVO = [
    "registro de produto",
    "registro sanitário",
    "registro sanitario",
    "registro administrativo",
    "registro no cadastro",
    "registro cadastral",
    "registro perante",
    "registro junto",
    "registro no sistema",
    "registro de preço",
    "registro de preco",
    "registro de preços",
    "registro de precos",
    "registro oficial",
    "registro público",
    "registro publico",
]

ORGAOS_REGULADORES_RELEVANTES = [
    "inmetro",
    "anvisa",
    "ibama",
    "receita federal",
    "secretaria especial da receita federal",
    "ministério do desenvolvimento",
    "ministerio do desenvolvimento",
    "mdic",
    "senacon",
    "secretaria nacional do consumidor",
    "cade",
    "aneel",
    "ana",
    "abnt",
    "conmetro",
    "denatran",
    "senatran",
    "mapa",
    "ministério da agricultura",
    "ministerio da agricultura",
]


# ============================================================
# UTILITÁRIOS GERAIS
# ============================================================

def garantir_pastas_saida() -> None:
    PASTA_SAIDA_BOLETINS.mkdir(parents=True, exist_ok=True)
    PASTA_PROMPTS_IA.mkdir(parents=True, exist_ok=True)


def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip()
    texto = re.sub(r"\s+", " ", texto)

    return texto


def normalizar_texto_busca(valor: Any) -> str:
    texto = normalizar_texto(valor).lower()

    substituicoes = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "ä": "a",
        "é": "e",
        "ê": "e",
        "è": "e",
        "ë": "e",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ï": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ò": "o",
        "ö": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
    }

    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)

    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def data_para_iso(valor: Any) -> str:
    if valor is None:
        return ""

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")

    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")

    texto = normalizar_texto(valor)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return texto

    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", texto):
        try:
            return datetime.strptime(texto, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return texto

    return texto


def converter_para_date(valor: date | str) -> date:
    if isinstance(valor, date):
        return valor

    data_iso = data_para_iso(valor)

    return datetime.strptime(data_iso, "%Y-%m-%d").date()


def eh_fim_de_semana(data_item: date) -> bool:
    return data_item.weekday() >= 5


def gerar_datas_periodo(data_inicio: date, data_fim: date) -> List[date]:
    if data_fim < data_inicio:
        raise ValueError("data_fim não pode ser menor que data_inicio.")

    datas: List[date] = []
    atual = data_inicio

    while atual <= data_fim:
        datas.append(atual)
        atual += timedelta(days=1)

    return datas


def carregar_json(caminho: Path) -> Any:
    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def salvar_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def salvar_txt(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with caminho.open("w", encoding="utf-8") as arquivo:
        arquivo.write(texto)


def termo_exato_encontrado(texto: str, termo: str) -> bool:
    """
    Busca termo com fronteira de palavra.

    Evita falso positivo como:
    - "porta" dentro de "aeroporto"
    - "ana" dentro de outro termo maior

    Para termos compostos, respeita espaços flexíveis.
    """
    texto_busca = normalizar_texto_busca(texto)
    termo_busca = normalizar_texto_busca(termo)

    if not termo_busca:
        return False

    partes = [re.escape(parte) for parte in termo_busca.split()]
    padrao_termo = r"\s+".join(partes)

    padrao = rf"(?<![a-z0-9]){padrao_termo}(?![a-z0-9])"

    return re.search(padrao, texto_busca, flags=re.IGNORECASE) is not None


def contem_qualquer(texto: str, termos: List[str]) -> bool:
    for termo in termos:
        if termo_exato_encontrado(texto, termo):
            return True

    return False


def termos_encontrados(texto: str, termos: List[str]) -> List[str]:
    encontrados: List[str] = []

    for termo in termos:
        if termo_exato_encontrado(texto, termo):
            encontrados.append(termo)

    return sorted(set(encontrados))


def primeiro_valor(dados: Dict[str, Any], chaves: List[str], padrao: Any = "") -> Any:
    for chave in chaves:
        if chave in dados and dados.get(chave) not in [None, ""]:
            return dados.get(chave)

    return padrao


def tem_contexto_produto_ambiguidade(texto: str, termo: str) -> bool:
    """
    Valida termos ambíguos que só devem contar como produto
    em contexto material.

    Exemplos:
    - porta não pode entrar por causa de aeroporto.
    - registro não pode entrar como produto quando for registro sanitário.
    - químico/quimico não deve sustentar produto sozinho.
    """
    termo_norm = normalizar_texto_busca(termo)

    if termo_norm in ["porta", "portas"]:
        return (
            termo_exato_encontrado(texto, termo)
            and contem_qualquer(texto, CONTEXTOS_PORTA_PRODUTO)
        )

    if termo_norm in ["registro", "registros"]:
        if contem_qualquer(texto, CONTEXTOS_REGISTRO_ADMINISTRATIVO):
            return False

        return (
            termo_exato_encontrado(texto, termo)
            and contem_qualquer(texto, CONTEXTOS_REGISTRO_PRODUTO)
        )

    if termo_norm in ["quimico", "quimicos", "químico", "químicos"]:
        return (
            termo_exato_encontrado(texto, termo)
            and contem_qualquer(texto, CONTEXTOS_QUIMICO_PRODUTO)
        )

    return termo_exato_encontrado(texto, termo)


def termos_produto_encontrados(texto: str) -> Dict[str, Any]:
    """
    Retorna produtos fortes, ambíguos validados e ambíguos rejeitados.
    """
    fortes = termos_encontrados(texto, TERMOS_PRODUTOS_LEROY_FORTES)

    ambiguos_validados: List[str] = []
    ambiguos_rejeitados: List[str] = []

    for termo in TERMOS_PRODUTOS_AMBIGUOS:
        if not termo_exato_encontrado(texto, termo):
            continue

        if tem_contexto_produto_ambiguidade(texto, termo):
            ambiguos_validados.append(termo)
        else:
            ambiguos_rejeitados.append(termo)

    return {
        "fortes": sorted(set(fortes)),
        "ambiguos_validados": sorted(set(ambiguos_validados)),
        "ambiguos_rejeitados": sorted(set(ambiguos_rejeitados)),
        "todos_validos": sorted(set(fortes + ambiguos_validados)),
    }


def termos_certificacao_encontrados(texto: str) -> Dict[str, Any]:
    """
    Separa termos fortes de certificação de termos ambíguos.
    """
    fortes = termos_encontrados(texto, TERMOS_CERTIFICACAO_SEGURANCA)
    ambiguos = termos_encontrados(texto, TERMOS_CERTIFICACAO_AMBIGUOS)

    return {
        "fortes": fortes,
        "ambiguos": ambiguos,
        "todos": sorted(set(fortes + ambiguos)),
    }


# ============================================================
# LOCALIZAÇÃO DE ARQUIVOS
# ============================================================

def caminho_relatorio_modelo_data(data_publicacao: date | str) -> Path:
    data_iso = data_para_iso(data_publicacao)

    return (
        PASTA_RELATORIOS_INFORMATIVOS
        / f"relatorio_executivo_modelo_{data_iso}.json"
    )


def caminho_match_data(data_publicacao: date | str) -> Path:
    data_iso = data_para_iso(data_publicacao)

    return (
        PASTA_MATCH_INFORMATIVOS
        / f"match_publicacoes_{data_iso}.json"
    )


def caminho_consolidado_periodo(data_inicio: date | str, data_fim: date | str) -> Path:
    inicio = data_para_iso(data_inicio)
    fim = data_para_iso(data_fim)

    return (
        PASTA_CONSOLIDADOS_PERIODO
        / f"consolidado_informativos_{inicio}_a_{fim}.json"
    )


def caminho_base_publicacoes_data(data_publicacao: date | str) -> Path:
    """
    Caminho da base diária completa de publicações.

    Esta base costuma conter o texto integral/parseado da publicação,
    que pode não estar presente no consolidado do período.
    """
    data_iso = data_para_iso(data_publicacao)

    return (
        PASTA_BASE_PUBLICACOES
        / f"base_publicacoes_{data_iso}.json"
    )


def resolver_fontes_periodo(
    data_inicio: date | str,
    data_fim: date | str,
    preferir_consolidado: bool = True,
) -> Dict[str, Any]:
    """
    Resolve quais arquivos serão usados como origem da curadoria.

    Preferência:
    1. consolidado do período, se existir;
    2. relatórios diários da finalidade informativos;
    3. match diário, se necessário.
    """
    inicio = converter_para_date(data_inicio)
    fim = converter_para_date(data_fim)

    consolidado = caminho_consolidado_periodo(inicio, fim)

    fontes: Dict[str, Any] = {
        "usar_consolidado": False,
        "consolidado": str(consolidado),
        "relatorios_modelo": [],
        "matches": [],
        "dias_uteis": [],
        "dias_ignorados_fim_de_semana": [],
        "dias_sem_arquivo": [],
    }

    if preferir_consolidado and consolidado.exists():
        fontes["usar_consolidado"] = True
        return fontes

    for data_item in gerar_datas_periodo(inicio, fim):
        data_iso = data_para_iso(data_item)

        if eh_fim_de_semana(data_item):
            fontes["dias_ignorados_fim_de_semana"].append(data_iso)
            continue

        fontes["dias_uteis"].append(data_iso)

        relatorio = caminho_relatorio_modelo_data(data_item)
        match = caminho_match_data(data_item)

        encontrou_algum = False

        if relatorio.exists():
            fontes["relatorios_modelo"].append(str(relatorio))
            encontrou_algum = True

        if match.exists():
            fontes["matches"].append(str(match))
            encontrou_algum = True

        if not encontrou_algum:
            fontes["dias_sem_arquivo"].append(data_iso)

    return fontes


# ============================================================
# EXTRAÇÃO ROBUSTA DE PUBLICAÇÕES
# ============================================================

def parece_publicacao(dados: Dict[str, Any]) -> bool:
    """
    Heurística para identificar se um dicionário parece ser uma publicação.
    """
    chaves = set(dados.keys())

    chaves_titulo = {"titulo", "title", "nome", "ementa"}
    chaves_texto = {
        "texto",
        "texto_integral",
        "conteudo",
        "resumo",
        "descricao",
        "texto_publicacao",
    }
    chaves_origem = {"orgao", "órgão", "fonte", "url", "link", "data_publicacao"}

    return (
        bool(chaves.intersection(chaves_titulo))
        and (
            bool(chaves.intersection(chaves_texto))
            or bool(chaves.intersection(chaves_origem))
        )
    )


def extrair_listas_publicacoes_recursivo(dados: Any) -> List[Dict[str, Any]]:
    """
    Busca publicações em estruturas JSON variadas.
    """
    publicacoes: List[Dict[str, Any]] = []

    if isinstance(dados, list):
        for item in dados:
            publicacoes.extend(extrair_listas_publicacoes_recursivo(item))

        return publicacoes

    if not isinstance(dados, dict):
        return publicacoes

    if parece_publicacao(dados):
        publicacoes.append(dados)

    for valor in dados.values():
        if isinstance(valor, (dict, list)):
            publicacoes.extend(extrair_listas_publicacoes_recursivo(valor))

    return publicacoes


def extrair_publicacoes_de_arquivo(caminho: Path) -> List[Dict[str, Any]]:
    dados = carregar_json(caminho)

    publicacoes = extrair_listas_publicacoes_recursivo(dados)

    publicacoes_unicas: Dict[str, Dict[str, Any]] = {}

    for item in publicacoes:
        chave = (
            normalizar_texto(
                primeiro_valor(item, ["id_publicacao", "id", "url", "link", "titulo"])
            )
            + "|"
            + normalizar_texto(primeiro_valor(item, ["titulo", "title", "nome"]))
        )

        if chave not in publicacoes_unicas:
            publicacoes_unicas[chave] = item

    return list(publicacoes_unicas.values())


def normalizar_chave_comparacao(valor: Any) -> str:
    """
    Normaliza identificadores para comparação entre consolidado e base diária.
    """
    texto = normalizar_texto_busca(valor)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def montar_chaves_publicacao(publicacao: Dict[str, Any]) -> List[str]:
    """
    Monta chaves possíveis para cruzar uma publicação entre arquivos.
    Prioriza id, url e título.
    """
    candidatos = [
        primeiro_valor(publicacao, ["id_publicacao", "id", "id_dou", "hash_conteudo"]),
        primeiro_valor(publicacao, ["url", "link", "href"]),
        primeiro_valor(publicacao, ["titulo", "title", "nome", "ementa"]),
    ]

    chaves: List[str] = []

    for candidato in candidatos:
        chave = normalizar_chave_comparacao(candidato)
        if chave and chave not in chaves:
            chaves.append(chave)

    return chaves


def publicacao_tem_texto_util(publicacao: Dict[str, Any]) -> bool:
    """
    Verifica se a publicação já possui conteúdo textual além do título.
    """
    titulo = normalizar_texto(
        primeiro_valor(publicacao, ["titulo", "title", "nome", "ementa"])
    ).lower()

    for chave in ["texto_integral", "texto", "conteudo", "texto_publicacao", "resumo", "descricao"]:
        valor = normalizar_texto(publicacao.get(chave))
        if valor and valor.lower() != titulo and len(valor) > 40:
            return True

    return False


def carregar_indice_base_diaria(data_publicacao: date | str) -> Dict[str, Dict[str, Any]]:
    """
    Carrega a base diária completa e indexa publicações por id/url/título.

    Se a base diária não existir, retorna índice vazio sem quebrar a execução.
    """
    caminho = caminho_base_publicacoes_data(data_publicacao)

    if not caminho.exists():
        return {}

    try:
        publicacoes_base = extrair_publicacoes_de_arquivo(caminho)
    except Exception:
        return {}

    indice: Dict[str, Dict[str, Any]] = {}

    for publicacao in publicacoes_base:
        for chave in montar_chaves_publicacao(publicacao):
            if chave and chave not in indice:
                indice[chave] = publicacao

    return indice


def complementar_publicacao_com_base_diaria(
    publicacao: Dict[str, Any],
    indices_base: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Complementa uma publicação do consolidado com campos da base diária.

    A regra é conservadora:
    - preserva os campos já existentes no consolidado;
    - só preenche campos vazios com dados da base diária;
    - adiciona metadado de complemento quando encontra correspondência.
    """
    if publicacao_tem_texto_util(publicacao):
        return publicacao

    publicacao_base: Optional[Dict[str, Any]] = None

    for chave in montar_chaves_publicacao(publicacao):
        if chave in indices_base:
            publicacao_base = indices_base[chave]
            break

    if not publicacao_base:
        return publicacao

    campos_para_complementar = [
        "texto_integral",
        "texto",
        "conteudo",
        "texto_publicacao",
        "resumo",
        "descricao",
        "ementa",
        "orgao",
        "órgão",
        "url",
        "link",
        "href",
        "data_publicacao",
        "titulo",
        "title",
        "nome",
    ]

    for campo in campos_para_complementar:
        if publicacao.get(campo) in [None, "", [], {}] and publicacao_base.get(campo) not in [None, "", [], {}]:
            publicacao[campo] = publicacao_base.get(campo)

    metadados = publicacao.get("metadados")
    if not isinstance(metadados, dict):
        metadados = {}

    metadados["complementado_base_diaria"] = True
    metadados["origem_complemento"] = "base_publicacoes_diaria"
    publicacao["metadados"] = metadados

    return publicacao


def complementar_publicacoes_com_bases_diarias(
    publicacoes: List[Dict[str, Any]],
    data_inicio: date | str,
    data_fim: date | str,
) -> List[Dict[str, Any]]:
    """
    Complementa publicações com texto da base diária completa do DOU.

    Isso permite que o pré-boletim extraia o "Trecho relevante" mesmo quando
    o consolidado do período não contém texto_integral/conteudo.
    """
    inicio = converter_para_date(data_inicio)
    fim = converter_para_date(data_fim)

    indices_base: Dict[str, Dict[str, Any]] = {}

    for data_item in gerar_datas_periodo(inicio, fim):
        indice_data = carregar_indice_base_diaria(data_item)
        indices_base.update({
            chave: valor
            for chave, valor in indice_data.items()
            if chave not in indices_base
        })

    if not indices_base:
        return publicacoes

    return [
        complementar_publicacao_com_base_diaria(publicacao, indices_base)
        for publicacao in publicacoes
    ]



def montar_chaves_item_boletim(item: ItemBoletimInformativo) -> List[str]:
    """
    Monta chaves possíveis para cruzar um item já classificado com a base diária.

    Importante:
    - usado somente para buscar texto complementar;
    - não altera classificação, relevância, seção ou visão executiva.
    """
    candidatos = [
        item.id_publicacao,
        item.url,
        item.titulo,
    ]

    chaves: List[str] = []

    for candidato in candidatos:
        chave = normalizar_chave_comparacao(candidato)
        if chave and chave not in chaves:
            chaves.append(chave)

    return chaves


def extrair_texto_util_publicacao_base(publicacao: Dict[str, Any]) -> str:
    """
    Extrai texto útil da publicação da base diária.

    A prioridade é texto integral/conteúdo. O título isolado não é aceito como
    texto útil, porque não serve para gerar trecho relevante.
    """
    titulo = normalizar_texto(
        primeiro_valor(publicacao, ["titulo", "title", "nome", "ementa"])
    ).lower()

    for chave in [
        "texto_integral",
        "texto",
        "conteudo",
        "texto_publicacao",
        "resumo",
        "descricao",
        "ementa",
    ]:
        valor = normalizar_texto(publicacao.get(chave))

        if valor and valor.lower() != titulo and len(valor) > 40:
            return valor

    return ""


def complementar_item_com_texto_base_diaria(
    item: ItemBoletimInformativo,
    indices_base: Dict[str, Dict[str, Any]],
) -> ItemBoletimInformativo:
    """
    Complementa um item JÁ CLASSIFICADO com texto da base diária.

    Regra de segurança:
    - NÃO altera nivel_relevancia;
    - NÃO altera classificacao_relacao;
    - NÃO altera secao_boletim;
    - NÃO altera descartado;
    - NÃO altera visao_executiva;
    - NÃO altera recomendação/decisão do match.

    O complemento fica apenas em metadados["texto_complementar_base_diaria"].
    """
    if not isinstance(item.metadados, dict):
        item.metadados = {}

    # Snapshot de segurança para garantir que nada técnico será alterado.
    snapshot_classificacao = {
        "secao_boletim": item.secao_boletim,
        "classificacao_relacao": item.classificacao_relacao,
        "nivel_relevancia": item.nivel_relevancia,
        "descartado": item.descartado,
        "motivo_descarte": item.motivo_descarte,
        "visao_executiva": item.metadados.get("visao_executiva", ""),
    }

    publicacao_base: Optional[Dict[str, Any]] = None

    for chave in montar_chaves_item_boletim(item):
        if chave in indices_base:
            publicacao_base = indices_base[chave]
            break

    if publicacao_base:
        texto_complementar = extrair_texto_util_publicacao_base(publicacao_base)

        if texto_complementar:
            item.metadados["texto_complementar_base_diaria"] = texto_complementar
            item.metadados["complementado_base_diaria"] = True
            item.metadados["origem_complemento"] = "base_publicacoes_diaria"

    # Reaplica o snapshot por segurança absoluta.
    item.secao_boletim = snapshot_classificacao["secao_boletim"]
    item.classificacao_relacao = snapshot_classificacao["classificacao_relacao"]
    item.nivel_relevancia = snapshot_classificacao["nivel_relevancia"]
    item.descartado = snapshot_classificacao["descartado"]
    item.motivo_descarte = snapshot_classificacao["motivo_descarte"]
    item.metadados["visao_executiva"] = snapshot_classificacao["visao_executiva"]

    return item


def complementar_itens_com_texto_base_diaria(
    itens: List[ItemBoletimInformativo],
    data_inicio: date | str,
    data_fim: date | str,
) -> List[ItemBoletimInformativo]:
    """
    Complementa itens já classificados com texto da base diária.

    Esta função é deliberadamente posterior à classificação.
    Ela serve apenas para melhorar o campo "Trecho relevante" do TXT.
    """
    inicio = converter_para_date(data_inicio)
    fim = converter_para_date(data_fim)

    indices_base: Dict[str, Dict[str, Any]] = {}

    for data_item in gerar_datas_periodo(inicio, fim):
        indice_data = carregar_indice_base_diaria(data_item)
        indices_base.update({
            chave: valor
            for chave, valor in indice_data.items()
            if chave not in indices_base
        })

    if not indices_base:
        return itens

    return [
        complementar_item_com_texto_base_diaria(item, indices_base)
        for item in itens
    ]




def carregar_publicacoes_periodo(
    data_inicio: date | str,
    data_fim: date | str,
    preferir_consolidado: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fontes = resolver_fontes_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        preferir_consolidado=preferir_consolidado,
    )

    publicacoes: List[Dict[str, Any]] = []

    if fontes["usar_consolidado"]:
        caminho = Path(fontes["consolidado"])
        publicacoes.extend(extrair_publicacoes_de_arquivo(caminho))
    else:
        caminhos = [
            Path(caminho)
            for caminho in fontes["relatorios_modelo"]
        ]

        caminhos.extend([
            Path(caminho)
            for caminho in fontes["matches"]
        ])

        for caminho in caminhos:
            publicacoes.extend(extrair_publicacoes_de_arquivo(caminho))

    publicacoes_unicas: Dict[str, Dict[str, Any]] = {}

    for item in publicacoes:
        id_publicacao = normalizar_texto(
            primeiro_valor(item, ["id_publicacao", "id", "id_dou"])
        )

        url = normalizar_texto(primeiro_valor(item, ["url", "link", "href"]))
        titulo = normalizar_texto(primeiro_valor(item, ["titulo", "title", "nome"]))

        chave = id_publicacao or url or titulo

        if not chave:
            chave = json.dumps(item, ensure_ascii=False, sort_keys=True)[:300]

        if chave not in publicacoes_unicas:
            publicacoes_unicas[chave] = item
        else:
            publicacoes_unicas[chave].update({
                k: v for k, v in item.items()
                if v not in [None, "", [], {}]
            })

    # ATENÇÃO:
    # Nesta etapa NÃO complementamos a publicação antes da classificação.
    # A classificação/visão executiva deve permanecer exatamente como veio
    # da regra de match/curadoria original.
    #
    # A base diária será usada depois, somente para enriquecer texto de apoio
    # do pré-boletim, sem reclassificar nada.
    publicacoes_final = list(publicacoes_unicas.values())

    return publicacoes_final, fontes


# ============================================================
# CLASSIFICAÇÃO DE CURADORIA
# ============================================================

def montar_texto_publicacao(publicacao: Dict[str, Any]) -> str:
    partes = [
        primeiro_valor(publicacao, ["titulo", "title", "nome", "ementa"]),
        primeiro_valor(publicacao, ["orgao", "órgão", "entidade", "ministerio"]),
        primeiro_valor(publicacao, ["resumo", "descricao", "ementa"]),
        primeiro_valor(
            publicacao,
            ["texto_integral", "texto", "conteudo", "texto_publicacao"],
        ),
        json.dumps(publicacao.get("palavras_chave_detectadas", []), ensure_ascii=False),
        json.dumps(publicacao.get("termos_detectados", []), ensure_ascii=False),
    ]

    return " ".join(normalizar_texto(parte) for parte in partes if parte)


def extrair_campos_publicacao(publicacao: Dict[str, Any]) -> Dict[str, Any]:
    data_publicacao = primeiro_valor(
        publicacao,
        [
            "data_publicacao",
            "data",
            "data_execucao",
            "data_dou",
            "dt_publicacao",
        ],
    )

    titulo = primeiro_valor(
        publicacao,
        ["titulo", "title", "nome", "ementa"],
    )

    orgao = primeiro_valor(
        publicacao,
        ["orgao", "órgão", "entidade", "ministerio", "unidade"],
    )

    url = primeiro_valor(
        publicacao,
        ["url", "link", "href"],
    )

    texto = primeiro_valor(
        publicacao,
        ["texto_integral", "texto", "conteudo", "texto_publicacao", "resumo"],
    )

    id_publicacao = primeiro_valor(
        publicacao,
        ["id_publicacao", "id", "id_dou", "hash_conteudo"],
    )

    fonte = primeiro_valor(
        publicacao,
        ["fonte", "origem"],
        "dou",
    )

    palavras = primeiro_valor(
        publicacao,
        ["palavras_chave_detectadas", "termos_detectados", "keywords"],
        [],
    )

    if not isinstance(palavras, list):
        palavras = [str(palavras)]

    return {
        "id_publicacao": normalizar_texto(id_publicacao),
        "fonte": normalizar_texto(fonte) or "dou",
        "data_publicacao": data_para_iso(data_publicacao),
        "titulo": normalizar_texto(titulo),
        "orgao": normalizar_texto(orgao),
        "url": normalizar_texto(url),
        "texto_referencia": normalizar_texto(texto),
        "palavras_chave_detectadas": palavras,
    }


def detectar_tipo_match(publicacao: Dict[str, Any]) -> str:
    """
    Tenta identificar tipo/categoria de match já calculado pelo match_service.
    """
    candidatos = [
        "tipo_match",
        "categoria_match",
        "classificacao_match",
        "classificacao",
        "categoria",
        "nivel_match",
        "grupo_match",
        "status_match",
    ]

    for chave in candidatos:
        valor = normalizar_texto(publicacao.get(chave))

        if valor:
            return valor.upper()

    return ""


def classificar_publicacao_para_boletim(
    publicacao: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Classifica publicação para o pré-boletim.

    Regra conservadora:
    - relação direta Leroy sempre alta;
    - produto forte + certificação/conformidade gera relevância média;
    - produto ambíguo só entra se houver contexto material;
    - registro/químico não sustentam produto sozinhos;
    - órgão regulador sem tema/produto fica como baixa relevância;
    - item sem relação material é descartado.
    """
    campos = extrair_campos_publicacao(publicacao)
    texto_total = montar_texto_publicacao(publicacao)
    tipo_match = detectar_tipo_match(publicacao)

    resumo_tecnico = campos["texto_referencia"] or campos["titulo"]

    termos_leroy = termos_encontrados(texto_total, TERMOS_LEROY)
    produtos_info = termos_produto_encontrados(texto_total)
    cert_info = termos_certificacao_encontrados(texto_total)

    termos_produto_validos = produtos_info["todos_validos"]
    termos_produto_fortes = produtos_info["fortes"]
    termos_produto_ambiguos_validados = produtos_info["ambiguos_validados"]
    termos_produto_ambiguos_rejeitados = produtos_info["ambiguos_rejeitados"]

    termos_cert_fortes = cert_info["fortes"]
    termos_cert_ambiguos = cert_info["ambiguos"]

    termos_import = termos_encontrados(texto_total, TERMOS_IMPORTACAO_COMERCIO)
    termos_orgao = termos_encontrados(
        campos["orgao"] + " " + texto_total,
        ORGAOS_REGULADORES_RELEVANTES,
    )

    evidencias_ambiguas_rejeitadas = [
        f"Termo ambíguo não usado como produto sem contexto: {termo}"
        for termo in termos_produto_ambiguos_rejeitados
    ]

    if termos_leroy:
        evidencias = [f"Menção Leroy: {termo}" for termo in termos_leroy]

        return {
            "secao_boletim": SECAO_PUBLICACOES_DIRETAS_LEROY,
            "classificacao_relacao": RELACAO_DIRETA_LEROY,
            "nivel_relevancia": RELEVANCIA_ALTA,
            "tema": "Relação direta com Leroy",
            "produto_assunto": "Leroy Merlin",
            "risco_oportunidade": "Publicação com menção direta à empresa ou possível relação explícita.",
            "recomendacao_acompanhamento": "Avaliar impacto direto e necessidade de providência interna.",
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": "A publicação possui menção direta à Leroy.",
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_cert_fortes and termos_produto_validos:
        evidencias = []
        evidencias.extend([
            f"Termo certificação/conformidade: {termo}"
            for termo in termos_cert_fortes[:10]
        ])
        evidencias.extend([
            f"Produto/assunto validado: {termo}"
            for termo in termos_produto_validos[:10]
        ])
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_NORMAS_CERTIFICACOES_SEGURANCA,
            "classificacao_relacao": CERTIFICACAO_SEGURANCA_CONFORMIDADE,
            "nivel_relevancia": RELEVANCIA_MEDIA,
            "tema": "Certificação, segurança e conformidade de produtos",
            "produto_assunto": ", ".join(termos_produto_validos[:5]),
            "risco_oportunidade": (
                "Pode indicar alteração, exigência ou acompanhamento técnico "
                "relacionado a produtos potencialmente comercializados."
            ),
            "recomendacao_acompanhamento": (
                "Verificar se os produtos citados fazem parte do sortimento ou "
                "da cadeia de fornecedores acompanhada."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação combina termos fortes de certificação/segurança/conformidade "
                "com produto ou categoria validada por contexto."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_produto_fortes:
        evidencias = [
            f"Produto/assunto forte: {termo}"
            for termo in termos_produto_fortes[:10]
        ]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_PRODUTOS_COMERCIALIZADOS,
            "classificacao_relacao": PRODUTO_COMERCIALIZADO,
            "nivel_relevancia": RELEVANCIA_MEDIA,
            "tema": "Produto potencialmente comercializado",
            "produto_assunto": ", ".join(termos_produto_fortes[:5]),
            "risco_oportunidade": (
                "Pode ter relação com produto ou categoria comercializada, "
                "dependendo do escopo da publicação."
            ),
            "recomendacao_acompanhamento": (
                "Confirmar se o produto/categoria tem relação prática com Leroy."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação contém produto ou categoria forte potencialmente comercializada."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_produto_ambiguos_validados:
        evidencias = [
            f"Produto ambíguo validado por contexto: {termo}"
            for termo in termos_produto_ambiguos_validados[:10]
        ]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_PRODUTOS_COMERCIALIZADOS,
            "classificacao_relacao": PRODUTO_COMERCIALIZADO,
            "nivel_relevancia": RELEVANCIA_BAIXA,
            "tema": "Produto potencialmente comercializado com validação contextual",
            "produto_assunto": ", ".join(termos_produto_ambiguos_validados[:5]),
            "risco_oportunidade": (
                "O termo de produto é ambíguo, mas apareceu com contexto material mínimo."
            ),
            "recomendacao_acompanhamento": (
                "Revisar manualmente antes de destacar no boletim final."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação contém termo de produto ambíguo validado por contexto."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_cert_fortes:
        evidencias = [
            f"Certificação/conformidade: {termo}"
            for termo in termos_cert_fortes[:10]
        ]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_NORMAS_CERTIFICACOES_SEGURANCA,
            "classificacao_relacao": CERTIFICACAO_SEGURANCA_CONFORMIDADE,
            "nivel_relevancia": RELEVANCIA_BAIXA,
            "tema": "Normas, certificação, segurança ou conformidade",
            "produto_assunto": "",
            "risco_oportunidade": (
                "Tema regulatório relevante, mas sem produto ou relação direta "
                "identificada automaticamente."
            ),
            "recomendacao_acompanhamento": (
                "Manter em monitoramento e validar relação material antes de destacar no boletim final."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação contém termos regulatórios fortes de certificação, segurança ou conformidade."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_import:
        evidencias = [
            f"Importação/comércio: {termo}"
            for termo in termos_import[:10]
        ]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_IMPORTACAO_COMERCIO_REGULACAO,
            "classificacao_relacao": IMPORTACAO_COMERCIO_REGULACAO,
            "nivel_relevancia": RELEVANCIA_BAIXA,
            "tema": "Importação, comércio ou regulação econômica",
            "produto_assunto": "",
            "risco_oportunidade": (
                "Pode afetar acompanhamento regulatório ou comercial, dependendo do produto/setor."
            ),
            "recomendacao_acompanhamento": (
                "Validar se há relação com mercadorias, fornecedores ou categorias acompanhadas."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação contém termos ligados a importação, comércio exterior ou regulação econômica."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if termos_orgao:
        evidencias = [
            f"Órgão regulador: {termo}"
            for termo in termos_orgao[:10]
        ]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_ORGAOS_REGULADORES,
            "classificacao_relacao": ORGAO_REGULADOR_RELEVANTE,
            "nivel_relevancia": RELEVANCIA_BAIXA,
            "tema": "Órgão regulador relevante",
            "produto_assunto": "",
            "risco_oportunidade": (
                "Publicação de órgão relevante, mas sem relação específica detectada automaticamente."
            ),
            "recomendacao_acompanhamento": (
                "Manter como monitoramento setorial ou descartar após revisão."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação está associada a órgão regulador relevante para acompanhamento."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    if "MONITORAMENTO" in tipo_match or "SETORIAL" in tipo_match:
        evidencias = ["Classificação original indica monitoramento setorial."]
        evidencias.extend(evidencias_ambiguas_rejeitadas)

        return {
            "secao_boletim": SECAO_MONITORAMENTO_SETORIAL,
            "classificacao_relacao": MONITORAMENTO_SETORIAL,
            "nivel_relevancia": RELEVANCIA_BAIXA,
            "tema": "Monitoramento setorial",
            "produto_assunto": "",
            "risco_oportunidade": (
                "Item classificado como monitoramento setorial pelo match."
            ),
            "recomendacao_acompanhamento": (
                "Revisar se o item possui impacto prático ou se deve permanecer apenas como leitura de ambiente."
            ),
            "resumo_tecnico": resumo_tecnico,
            "motivo_relevancia": (
                "A publicação foi classificada como monitoramento setorial."
            ),
            "evidencias": evidencias,
            "descartado": False,
            "motivo_descarte": "",
        }

    evidencias_descarte = []
    evidencias_descarte.extend(evidencias_ambiguas_rejeitadas)

    if termos_cert_ambiguos:
        evidencias_descarte.extend([
            f"Termo certificação ambíguo sem força suficiente: {termo}"
            for termo in termos_cert_ambiguos
        ])

    return {
        "secao_boletim": SECAO_ITENS_DESCARTADOS,
        "classificacao_relacao": DESCARTADO_SEM_RELACAO_MATERIAL,
        "nivel_relevancia": RELEVANCIA_DESCARTADO,
        "tema": "Sem relação material detectada",
        "produto_assunto": "",
        "risco_oportunidade": "",
        "recomendacao_acompanhamento": "",
        "resumo_tecnico": resumo_tecnico,
        "motivo_relevancia": "",
        "evidencias": evidencias_descarte,
        "descartado": True,
        "motivo_descarte": (
            "Não foi identificada menção direta à Leroy, produto acompanhado "
            "com contexto suficiente, órgão regulador relevante ou tema regulatório material."
        ),
    }


def converter_publicacao_em_item_boletim(
    publicacao: Dict[str, Any],
    data_padrao: str = "",
) -> ItemBoletimInformativo:
    campos = extrair_campos_publicacao(publicacao)

    if not campos["data_publicacao"]:
        campos["data_publicacao"] = data_padrao

    classificacao = classificar_publicacao_para_boletim(publicacao)

    item = construir_item_boletim(
        id_publicacao=campos["id_publicacao"],
        fonte=campos["fonte"] or "dou",
        data_publicacao=campos["data_publicacao"],
        titulo=campos["titulo"],
        orgao=campos["orgao"],
        url=campos["url"],
        secao_boletim=classificacao["secao_boletim"],
        classificacao_relacao=classificacao["classificacao_relacao"],
        nivel_relevancia=classificacao["nivel_relevancia"],
        resumo_tecnico=classificacao["resumo_tecnico"],
        motivo_relevancia=classificacao["motivo_relevancia"],
        tema=classificacao["tema"],
        produto_assunto=classificacao["produto_assunto"],
        risco_oportunidade=classificacao["risco_oportunidade"],
        recomendacao_acompanhamento=classificacao["recomendacao_acompanhamento"],
        texto_referencia=campos["texto_referencia"],
        palavras_chave_detectadas=campos["palavras_chave_detectadas"],
        evidencias=classificacao["evidencias"],
        descartado=classificacao["descartado"],
        motivo_descarte=classificacao["motivo_descarte"],
        metadados={
            "publicacao_original_chaves": sorted(list(publicacao.keys())),
            "curadoria_origem": "curadoria_boletim_informativos_service",
        },
    )

    item.metadados["visao_executiva"] = classificar_visao_item_boletim(item)

    return item


# ============================================================
# VISÃO EXECUTIVA SOBRE OS ITENS CURADOS
# ============================================================

def classificar_visao_item_boletim(item: ItemBoletimInformativo) -> str:
    """
    Separa a classificação técnica da visão executiva do boletim.

    Regra:
    - ALTA: destaque executivo;
    - MEDIA: possível destaque / revisão;
    - BAIXA: monitoramento;
    - DESCARTADO: descartado;
    - demais casos: revisão humana.
    """
    if item.descartado or item.nivel_relevancia == RELEVANCIA_DESCARTADO:
        return VISAO_DESCARTADO

    if (
        item.nivel_relevancia == RELEVANCIA_ALTA
        or item.classificacao_relacao == RELACAO_DIRETA_LEROY
    ):
        return VISAO_DESTAQUE_EXECUTIVO

    if item.nivel_relevancia == RELEVANCIA_MEDIA:
        return VISAO_POSSIVEL_DESTAQUE_REVISAO

    if item.nivel_relevancia == RELEVANCIA_BAIXA:
        return VISAO_MONITORAMENTO

    return VISAO_REVISAO_HUMANA


def calcular_resumo_visao_executiva(
    itens: List[ItemBoletimInformativo],
) -> Dict[str, Any]:
    """
    Calcula a visão executiva do boletim.

    Isso evita que item de baixa relevância seja tratado como
    destaque real para o cliente.
    """
    grupos = {
        VISAO_DESTAQUE_EXECUTIVO: [],
        VISAO_POSSIVEL_DESTAQUE_REVISAO: [],
        VISAO_MONITORAMENTO: [],
        VISAO_DESCARTADO: [],
        VISAO_REVISAO_HUMANA: [],
    }

    for item in itens:
        visao = classificar_visao_item_boletim(item)
        item.metadados["visao_executiva"] = visao
        grupos[visao].append(item)

    return {
        "total_itens": len(itens),
        "total_destaques_executivos": len(grupos[VISAO_DESTAQUE_EXECUTIVO]),
        "total_possiveis_destaques_revisao": len(grupos[VISAO_POSSIVEL_DESTAQUE_REVISAO]),
        "total_monitoramento": len(grupos[VISAO_MONITORAMENTO]),
        "total_descartados": len(grupos[VISAO_DESCARTADO]),
        "total_revisao_humana": len(grupos[VISAO_REVISAO_HUMANA]),
        "grupos": {
            chave: [
                {
                    "id_item": item.id_item,
                    "titulo": item.titulo,
                    "data_publicacao": item.data_publicacao,
                    "orgao": item.orgao,
                    "nivel_relevancia": item.nivel_relevancia,
                    "classificacao_relacao": item.classificacao_relacao,
                    "secao_boletim": item.secao_boletim,
                }
                for item in valor
            ]
            for chave, valor in grupos.items()
        },
    }


def montar_sintese_visao_executiva(
    data_inicio: str,
    data_fim: str,
    total_publicacoes_lidas: int,
    resumo_visao: Dict[str, Any],
) -> str:
    destaques = resumo_visao.get("total_destaques_executivos", 0)
    possiveis = resumo_visao.get("total_possiveis_destaques_revisao", 0)
    monitoramento = resumo_visao.get("total_monitoramento", 0)
    descartados = resumo_visao.get("total_descartados", 0)
    revisao = resumo_visao.get("total_revisao_humana", 0)

    if destaques == 0 and possiveis == 0 and monitoramento > 0:
        return (
            f"No período de {data_inicio} a {data_fim}, foram analisadas "
            f"{total_publicacoes_lidas} publicação(ões). Não foram identificadas "
            f"publicações com relação direta ou impacto material confirmado para Leroy. "
            f"Foram encontrados {monitoramento} item(ns) de baixa relevância para "
            f"monitoramento regulatório, sem recomendação automática de destaque "
            f"executivo ao cliente. {descartados} item(ns) foram descartado(s)."
        )

    if destaques == 0 and possiveis > 0:
        return (
            f"No período de {data_inicio} a {data_fim}, foram analisadas "
            f"{total_publicacoes_lidas} publicação(ões). Não houve relação direta "
            f"confirmada com Leroy, mas {possiveis} item(ns) foram classificados "
            f"como possível destaque sujeito a revisão. Também há {monitoramento} "
            f"item(ns) de monitoramento e {descartados} item(ns) descartado(s)."
        )

    if destaques > 0:
        return (
            f"No período de {data_inicio} a {data_fim}, foram analisadas "
            f"{total_publicacoes_lidas} publicação(ões). A curadoria identificou "
            f"{destaques} destaque(s) executivo(s), {possiveis} possível(is) "
            f"destaque(s) para revisão, {monitoramento} item(ns) de monitoramento "
            f"e {descartados} item(ns) descartado(s)."
        )

    if total_publicacoes_lidas == 0:
        return (
            f"No período de {data_inicio} a {data_fim}, não foram localizadas "
            f"publicações para compor o pré-boletim."
        )

    return (
        f"No período de {data_inicio} a {data_fim}, foram analisadas "
        f"{total_publicacoes_lidas} publicação(ões). Não foram identificados "
        f"destaques executivos. O período contém {monitoramento} item(ns) de "
        f"monitoramento, {possiveis} possível(is) destaque(s) para revisão, "
        f"{revisao} item(ns) para revisão humana e {descartados} item(ns) descartado(s)."
    )


def montar_prompt_ia_com_visao_executiva(
    boletim: BoletimInformativo,
    resumo_visao: Dict[str, Any],
) -> str:
    """
    Acrescenta orientação executiva ao prompt gerado pelo modelo do boletim.
    """
    prompt_base = boletim.prompt_ia or ""

    linhas: List[str] = []

    linhas.append("ORIENTAÇÃO EXECUTIVA ADICIONAL")
    linhas.append("")
    linhas.append("Use a visão executiva abaixo para não tratar itens de baixa relevância como destaque principal.")
    linhas.append("")
    linhas.append(f"Destaques executivos: {resumo_visao.get('total_destaques_executivos', 0)}")
    linhas.append(f"Possíveis destaques para revisão: {resumo_visao.get('total_possiveis_destaques_revisao', 0)}")
    linhas.append(f"Itens de monitoramento: {resumo_visao.get('total_monitoramento', 0)}")
    linhas.append(f"Itens descartados: {resumo_visao.get('total_descartados', 0)}")
    linhas.append(f"Itens para revisão humana: {resumo_visao.get('total_revisao_humana', 0)}")
    linhas.append("")
    linhas.append("Regra de redação:")
    linhas.append("- Itens ALTA devem ser tratados como destaque executivo.")
    linhas.append("- Itens MEDIA devem ser tratados como possíveis destaques, com cautela.")
    linhas.append("- Itens BAIXA devem ser tratados como monitoramento setorial/regulatório.")
    linhas.append("- Itens DESCARTADO não devem entrar no corpo principal do boletim.")
    linhas.append("- Não afirme impacto para Leroy quando a curadoria indicar apenas monitoramento.")
    linhas.append("")

    if prompt_base:
        linhas.append("=" * 80)
        linhas.append("PROMPT ORIGINAL DO PRÉ-BOLETIM")
        linhas.append("=" * 80)
        linhas.append(prompt_base)

    return "\n".join(linhas)


# ============================================================
# GERAÇÃO DO BOLETIM
# ============================================================

def gerar_pre_boletim_informativos(
    data_inicio: date | str,
    data_fim: date | str,
    preferir_consolidado: bool = True,
    incluir_descartados: bool = True,
) -> Dict[str, Any]:
    """
    Gera pré-boletim informativo para dia ou período.

    Retorna dict com:
    - status;
    - boletim;
    - arquivos gerados;
    - fontes usadas.
    """
    garantir_pastas_saida()

    inicio = data_para_iso(data_inicio)
    fim = data_para_iso(data_fim)

    publicacoes, fontes = carregar_publicacoes_periodo(
        data_inicio=inicio,
        data_fim=fim,
        preferir_consolidado=preferir_consolidado,
    )

    itens: List[ItemBoletimInformativo] = []

    for publicacao in publicacoes:
        item = converter_publicacao_em_item_boletim(
            publicacao=publicacao,
            data_padrao=inicio,
        )

        if incluir_descartados:
            itens.append(item)
        elif not item.descartado:
            itens.append(item)

    # Complemento textual seguro:
    # A partir daqui os itens já estão classificados.
    # Esta etapa só adiciona texto auxiliar em metadados para o TXT.
    # Não pode reclassificar nem alterar a visão executiva.
    itens = complementar_itens_com_texto_base_diaria(
        itens=itens,
        data_inicio=inicio,
        data_fim=fim,
    )

    resumo_visao = calcular_resumo_visao_executiva(itens)

    boletim = construir_boletim_informativo(
        data_inicio=inicio,
        data_fim=fim,
        itens_curados=itens,
        total_publicacoes_analisadas=len(publicacoes),
        finalidade=FINALIDADE,
        titulo=f"Pré-boletim Informativo — {inicio} a {fim}",
        arquivos_origem=(
            [fontes["consolidado"]]
            if fontes.get("usar_consolidado")
            else fontes.get("relatorios_modelo", []) + fontes.get("matches", [])
        ),
        metadados={
            "fontes": fontes,
            "preferir_consolidado": preferir_consolidado,
            "incluir_descartados": incluir_descartados,
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "visao_executiva": resumo_visao,
        },
    )

    boletim.resumo_executivo.sintese_executiva = montar_sintese_visao_executiva(
        data_inicio=inicio,
        data_fim=fim,
        total_publicacoes_lidas=len(publicacoes),
        resumo_visao=resumo_visao,
    )

    boletim.observacoes_curadoria.append(
        "Itens de baixa relevância são tratados como monitoramento, não como destaque executivo."
    )

    boletim.prompt_ia = montar_prompt_ia_com_visao_executiva(
        boletim=boletim,
        resumo_visao=resumo_visao,
    )

    validacao = boletim.validar()

    nome_base = f"pre_boletim_informativos_{inicio}_a_{fim}"

    caminho_json = PASTA_SAIDA_BOLETINS / f"{nome_base}.json"
    caminho_txt = PASTA_SAIDA_BOLETINS / f"{nome_base}.txt"
    caminho_prompt = PASTA_PROMPTS_IA / f"prompt_ia_{nome_base}.txt"

    boletim.arquivos_saida = {
        "json": str(caminho_json),
        "txt": str(caminho_txt),
        "prompt_ia": str(caminho_prompt),
    }

    salvar_json(caminho_json, boletim.to_dict())
    salvar_txt(caminho_txt, montar_txt_boletim(boletim))
    salvar_txt(caminho_prompt, boletim.prompt_ia)

    status = "PRE_BOLETIM_GERADO"

    if not validacao["valido"]:
        status = "PRE_BOLETIM_GERADO_COM_ERROS_VALIDACAO"
    elif validacao["avisos"]:
        status = "PRE_BOLETIM_GERADO_COM_AVISOS"

    return {
        "status": status,
        "data_inicio": inicio,
        "data_fim": fim,
        "total_publicacoes_lidas": len(publicacoes),
        "total_itens_curados": len(itens),

        # Mantido por compatibilidade: total de itens não descartados.
        "total_relevantes": len([item for item in itens if not item.descartado]),
        "total_descartados": resumo_visao.get("total_descartados", 0),

        # Nova visão executiva.
        "total_destaques_executivos": resumo_visao.get("total_destaques_executivos", 0),
        "total_possiveis_destaques_revisao": resumo_visao.get(
            "total_possiveis_destaques_revisao",
            0,
        ),
        "total_monitoramento": resumo_visao.get("total_monitoramento", 0),
        "total_revisao_humana": resumo_visao.get("total_revisao_humana", 0),

        "validacao": validacao,
        "fontes": fontes,
        "visao_executiva": resumo_visao,
        "arquivos": boletim.arquivos_saida,
        "boletim": boletim.to_dict(),
    }



# ============================================================
# FORMATAÇÃO ENXUTA DO TXT — PRÉ-BOLETIM
# ============================================================

def formatar_data_br(valor: Any) -> str:
    """
    Converte YYYY-MM-DD para DD/MM/YYYY quando possível.
    """
    texto = data_para_iso(valor)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        try:
            return datetime.strptime(texto, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return texto

    return normalizar_texto(valor)


def limpar_texto_para_saida(texto: Any, limite: int = 1200) -> str:
    """
    Limpa texto para exibição no TXT do pré-boletim.
    """
    valor = normalizar_texto(texto)

    if not valor:
        return ""

    valor = re.sub(r"https?://\S+", "", valor)
    valor = re.sub(r"www\.\S+", "", valor)
    valor = re.sub(r"\s+", " ", valor).strip()

    if len(valor) <= limite:
        return valor

    return valor[: limite - 3].rstrip() + "..."


def obter_visao_executiva_item(item: ItemBoletimInformativo) -> str:
    """
    Obtém a visão executiva do item.
    """
    if item.metadados:
        visao = item.metadados.get("visao_executiva", "")
        if visao:
            return visao

    return classificar_visao_item_boletim(item)


def obter_decisao_sugerida_item(item: ItemBoletimInformativo) -> str:
    """
    Transforma a visão executiva em decisão simples para o pré-boletim.
    """
    visao = obter_visao_executiva_item(item)

    if visao == VISAO_DESTAQUE_EXECUTIVO:
        return "Incluir como destaque no boletim definitivo."

    if visao == VISAO_POSSIVEL_DESTAQUE_REVISAO:
        return "Revisar antes de decidir se entra no boletim definitivo."

    if visao == VISAO_MONITORAMENTO:
        return "Manter apenas como monitoramento."

    if visao == VISAO_DESCARTADO:
        return "Não incluir no boletim definitivo."

    if visao == VISAO_REVISAO_HUMANA:
        return "Analisar melhor antes de decidir."

    return "Revisar manualmente antes de decidir."


def obter_impacto_leroy_item(item: ItemBoletimInformativo) -> str:
    """
    Define o impacto para Leroy em linguagem simples.
    """
    visao = obter_visao_executiva_item(item)

    if item.classificacao_relacao == RELACAO_DIRETA_LEROY:
        return "Impacto direto ou relação explícita identificada automaticamente."

    if visao == VISAO_DESTAQUE_EXECUTIVO:
        return "Possível impacto relevante identificado automaticamente."

    if visao == VISAO_POSSIVEL_DESTAQUE_REVISAO:
        return "Possível impacto indireto. Requer validação antes do boletim definitivo."

    if visao == VISAO_MONITORAMENTO:
        return "Não identificado automaticamente."

    if visao == VISAO_DESCARTADO:
        return "Não identificado."

    return "Não identificado automaticamente."


def obter_o_que_e_item(item: ItemBoletimInformativo) -> str:
    """
    Gera uma descrição curta e objetiva da publicação, sem usar IA.
    """
    classificacao = item.classificacao_relacao
    tema = normalizar_texto(item.tema)
    orgao = normalizar_texto(item.orgao)

    if item.classificacao_relacao == RELACAO_DIRETA_LEROY:
        return (
            "Publicação com menção direta ou relação explícita com Leroy. "
            "Requer leitura prioritária para validação de impacto."
        )

    if classificacao == PRODUTO_COMERCIALIZADO:
        if item.produto_assunto:
            return (
                f"Publicação relacionada a possível produto ou categoria comercializada "
                f"({item.produto_assunto}). Não há impacto direto confirmado automaticamente."
            )

        return (
            "Publicação relacionada a possível produto ou categoria comercializada. "
            "Não há impacto direto confirmado automaticamente."
        )

    if classificacao == CERTIFICACAO_SEGURANCA_CONFORMIDADE:
        if "inmetro" in normalizar_texto_busca(orgao):
            return (
                "Publicação relacionada a qualidade, conformidade ou fiscalização. "
                "Não há produto Leroy identificado automaticamente."
            )

        return (
            "Publicação administrativa identificada por termos de certificação, "
            "conformidade ou regulação. Não há relação direta confirmada com Leroy."
        )

    if classificacao == IMPORTACAO_COMERCIO_REGULACAO:
        return (
            "Publicação regulatória identificada por termos de importação, exportação "
            "ou regulação econômica. Não há impacto direto confirmado para Leroy."
        )

    if classificacao == ORGAO_REGULADOR_RELEVANTE:
        return (
            "Publicação de órgão regulador relevante para acompanhamento. "
            "Não há impacto material confirmado automaticamente."
        )

    if classificacao == MONITORAMENTO_SETORIAL:
        return (
            "Publicação classificada como monitoramento setorial. "
            "Não há relação direta confirmada com Leroy."
        )

    if item.descartado or classificacao == DESCARTADO_SEM_RELACAO_MATERIAL:
        return (
            "Publicação sem relação material identificada automaticamente. "
            "Mantida apenas para rastreabilidade."
        )

    if tema:
        return (
            f"Publicação relacionada ao tema '{tema}'. "
            "Não há impacto direto confirmado automaticamente."
        )

    return (
        "Publicação identificada pela curadoria automática. "
        "Não há relação direta confirmada com Leroy."
    )


def extrair_termos_das_evidencias(item: ItemBoletimInformativo) -> List[str]:
    """
    Extrai termos úteis das evidências para buscar trecho relevante.
    """
    termos: List[str] = []

    for evidencia in item.evidencias or []:
        texto = normalizar_texto(evidencia)

        if ":" in texto:
            termo = texto.split(":", 1)[1].strip()
        else:
            termo = texto.strip()

        termo = termo.replace('"', "").replace("'", "").strip()

        if termo and len(termo) <= 80:
            termos.append(termo)

    for palavra in item.palavras_chave_detectadas or []:
        palavra_limpa = normalizar_texto(palavra)
        if palavra_limpa:
            termos.append(palavra_limpa)

    termos_prioritarios: List[str] = []

    for termo in termos:
        termo_norm = normalizar_texto_busca(termo)

        if not termo_norm:
            continue

        ja_existe = any(
            normalizar_texto_busca(item_existente) == termo_norm
            for item_existente in termos_prioritarios
        )

        if not ja_existe:
            termos_prioritarios.append(termo)

    return termos_prioritarios


def obter_texto_base_trecho(item: ItemBoletimInformativo) -> str:
    """
    Obtém o texto usado para extrair o trecho relevante.

    Prioridade:
    1. texto complementar da base diária, salvo em metadados;
    2. texto_referencia original do item;
    3. resumo_tecnico original;
    4. título apenas como último fallback.

    Observação:
    O texto complementar NÃO participa da classificação.
    Ele é usado exclusivamente para montar o trecho relevante do TXT.
    """
    texto_complementar = ""

    if isinstance(item.metadados, dict):
        texto_complementar = normalizar_texto(
            item.metadados.get("texto_complementar_base_diaria")
        )

    candidatos = [
        texto_complementar,
        item.texto_referencia,
        item.resumo_tecnico,
        item.titulo,
    ]

    for candidato in candidatos:
        texto = limpar_texto_para_saida(candidato, limite=10000)
        if texto:
            return texto

    return ""


def extrair_trecho_relevante_item(
    item: ItemBoletimInformativo,
    margem: int = 220,
) -> str:
    """
    Extrai trecho da publicação onde consta a palavra-chave/evidência.
    """
    texto = obter_texto_base_trecho(item)

    if not texto:
        return (
            "Trecho relevante não disponível no consolidado usado pelo pré-boletim. "
            "Validar a publicação pelo link oficial do DOU."
        )

    titulo_norm = normalizar_texto(item.titulo).lower()

    if texto.lower() == titulo_norm:
        return (
            "Trecho relevante não disponível no consolidado usado pelo pré-boletim. "
            "Validar a publicação pelo link oficial do DOU."
        )

    termos = extrair_termos_das_evidencias(item)
    texto_busca = normalizar_texto_busca(texto)

    for termo in termos:
        termo_busca = normalizar_texto_busca(termo)

        if not termo_busca:
            continue

        posicao = texto_busca.find(termo_busca)

        if posicao < 0:
            continue

        inicio = max(0, posicao - margem)
        fim = min(len(texto), posicao + len(termo) + margem)

        trecho = texto[inicio:fim].strip()

        if inicio > 0:
            trecho = "..." + trecho

        if fim < len(texto):
            trecho = trecho + "..."

        return trecho

    texto_limpo = limpar_texto_para_saida(texto, limite=500)

    if texto_limpo and texto_limpo.lower() != titulo_norm:
        return texto_limpo

    return (
        "Trecho relevante não disponível no consolidado usado pelo pré-boletim. "
        "Validar a publicação pelo link oficial do DOU."
    )




def extrair_trechos_relevantes_item(
    item: ItemBoletimInformativo,
    margem: int = 220,
) -> List[Tuple[str, str]]:
    """
    Extrai um ou mais trechos relevantes, um por palavra-chave encontrada.

    Esta função apenas melhora a exibição do TXT.
    Não altera classificação, relevância, seção, descartado ou visão executiva.
    """
    texto_base = obter_texto_base_trecho(item)

    if not texto_base:
        return [
            (
                "SEM_TRECHO",
                (
                    "Trecho relevante não disponível no consolidado/base usada pelo pré-boletim. "
                    "Validar a publicação pelo link oficial do DOU."
                ),
            )
        ]

    titulo_norm = normalizar_texto(item.titulo).lower()

    if texto_base.lower() == titulo_norm:
        return [
            (
                "SEM_TRECHO",
                (
                    "Trecho relevante não disponível no consolidado/base usada pelo pré-boletim. "
                    "Validar a publicação pelo link oficial do DOU."
                ),
            )
        ]

    palavras = obter_palavras_chave_match_item(item)
    texto_busca = normalizar_texto_busca(texto_base)

    trechos: List[Tuple[str, str]] = []
    intervalos_usados: List[Tuple[int, int]] = []

    for palavra in palavras:
        palavra_limpa = normalizar_texto(palavra)
        palavra_busca = normalizar_texto_busca(palavra_limpa)

        if not palavra_busca:
            continue

        posicao = texto_busca.find(palavra_busca)

        if posicao < 0:
            continue

        inicio = max(0, posicao - margem)
        fim = min(len(texto_base), posicao + len(palavra_limpa) + margem)

        intervalo_atual = (inicio, fim)
        trecho = texto_base[inicio:fim].strip()

        if inicio > 0:
            trecho = "..." + trecho

        if fim < len(texto_base):
            trecho = trecho + "..."

        # Se a palavra estiver em trecho praticamente igual ao anterior,
        # não duplica o bloco.
        duplicado = False
        for inicio_usado, fim_usado in intervalos_usados:
            inter_inicio = max(inicio, inicio_usado)
            inter_fim = min(fim, fim_usado)
            inter_tam = max(0, inter_fim - inter_inicio)
            tam_atual = max(1, fim - inicio)

            if inter_tam / tam_atual >= 0.80:
                duplicado = True
                break

        if duplicado:
            continue

        trechos.append((palavra_limpa, trecho))
        intervalos_usados.append(intervalo_atual)

    if trechos:
        return trechos

    texto_limpo = limpar_texto_para_saida(texto_base, limite=500)

    if texto_limpo and texto_limpo.lower() != titulo_norm:
        return [("SEM_PALAVRA_LOCALIZADA", texto_limpo)]

    return [
        (
            "SEM_TRECHO",
            (
                "Trecho relevante não disponível no consolidado/base usada pelo pré-boletim. "
                "Validar a publicação pelo link oficial do DOU."
            ),
        )
    ]



def avaliar_observacao_contexto_palavra_chave(
    palavra: str,
    trecho: str,
) -> str:
    """
    Avalia apenas o CONTEXTO DE EXIBIÇÃO da palavra-chave no trecho.

    Importante:
    - não altera match;
    - não altera classificação;
    - não altera relevância;
    - não altera visão executiva;
    - apenas ajuda o usuário a entender se a ocorrência parece genérica.
    """
    palavra_norm = normalizar_texto_busca(palavra)
    trecho_norm = normalizar_texto_busca(trecho)

    if not palavra_norm or not trecho_norm:
        return ""

    if palavra_norm == "conformidade":
        padroes_genericos = [
            "em conformidade com o disposto",
            "em conformidade com a legislacao",
            "em conformidade com a lei",
            "em conformidade com o art",
            "em conformidade com os termos",
        ]

        if any(padrao in trecho_norm for padrao in padroes_genericos):
            return (
                "Observação: a palavra-chave aparece em expressão administrativa/jurídica "
                "genérica, não necessariamente como conformidade de produto."
            )

    if palavra_norm == "processo":
        if "processo administrativo" in trecho_norm:
            return (
                "Observação: a palavra-chave aparece como processo administrativo, "
                "não necessariamente como tema regulatório material para Leroy."
            )

    if palavra_norm in ["registro", "registros"]:
        padroes_registro_generico = [
            "certificado de registro",
            "registro e autorizacao",
            "registro administrativo",
            "registro perante",
            "registro no cadastro",
        ]

        if any(padrao in trecho_norm for padrao in padroes_registro_generico):
            return (
                "Observação: a palavra-chave aparece em contexto de registro administrativo "
                "ou documental, exigindo validação de relação material."
            )

    if palavra_norm in ["autorizacao", "autorização"]:
        padroes_autorizacao_generica = [
            "sem autorizacao da autoridade",
            "autorizacao nominal",
            "autorizacao de importacao",
            "autorizacao de exportacao",
        ]

        if any(padrao in trecho_norm for padrao in padroes_autorizacao_generica):
            return (
                "Observação: a palavra-chave aparece em contexto administrativo ou documental; "
                "validar se há relação prática com produto, operação ou fornecedor."
            )

    return ""



def formatar_trechos_relevantes_item(item: ItemBoletimInformativo) -> List[str]:
    """
    Formata os trechos relevantes para o TXT.

    Quando há mais de uma palavra-chave localizada em partes diferentes
    do texto, imprime um trecho por palavra-chave.
    """
    trechos = extrair_trechos_relevantes_item(item)

    if len(trechos) == 1:
        palavra, trecho = trechos[0]

        if palavra in ["SEM_TRECHO", "SEM_PALAVRA_LOCALIZADA"]:
            return [trecho]

        return [
            f"Trecho 1 — {palavra}:",
            trecho,
        ]

    linhas: List[str] = []

    for indice, (palavra, trecho) in enumerate(trechos, start=1):
        linhas.append(f"Trecho {indice} — {palavra}:")
        linhas.append(trecho)

        observacao = avaliar_observacao_contexto_palavra_chave(
            palavra=palavra,
            trecho=trecho,
        )

        if observacao:
            linhas.append(observacao)

        if indice < len(trechos):
            linhas.append("")

    return linhas



def obter_palavras_chave_match_item(item: ItemBoletimInformativo) -> List[str]:
    """
    Retorna as palavras-chave/termos de match associados ao item.

    Importante:
    - apenas exibe rastreabilidade já existente;
    - não cria palavra-chave nova;
    - não valida;
    - não reclassifica.
    """
    palavras: List[str] = []

    for palavra in item.palavras_chave_detectadas or []:
        palavra_limpa = normalizar_texto(palavra)
        if palavra_limpa:
            palavras.append(palavra_limpa)

    for evidencia in item.evidencias or []:
        texto_evidencia = normalizar_texto(evidencia)

        if ":" in texto_evidencia:
            termo = texto_evidencia.split(":", 1)[1].strip()
        else:
            termo = texto_evidencia.strip()

        termo = termo.replace('"', "").replace("'", "").strip()

        # Evita levar frases explicativas longas como palavra-chave.
        if termo and len(termo) <= 80:
            palavras.append(termo)

    palavras_unicas: List[str] = []

    for palavra in palavras:
        chave = normalizar_texto_busca(palavra)

        if not chave:
            continue

        if not any(normalizar_texto_busca(item_existente) == chave for item_existente in palavras_unicas):
            palavras_unicas.append(palavra)

    return palavras_unicas


def formatar_palavras_chave_match_item(item: ItemBoletimInformativo) -> List[str]:
    """
    Formata as palavras-chave do match para o TXT do pré-boletim.
    """
    palavras = obter_palavras_chave_match_item(item)

    if not palavras:
        return ["- Palavra-chave não informada na origem do match."]

    return [f"- {palavra}" for palavra in palavras]



# ============================================================
# SAÍDA TXT
# ============================================================

def montar_txt_boletim(boletim: BoletimInformativo) -> str:
    """
    Monta o TXT do pré-boletim no formato enxuto validado.
    """
    linhas: List[str] = []

    resumo_visao = boletim.metadados.get("visao_executiva", {}) if boletim.metadados else {}

    destaques = resumo_visao.get("total_destaques_executivos", 0)
    possiveis = resumo_visao.get("total_possiveis_destaques_revisao", 0)
    monitoramento = resumo_visao.get("total_monitoramento", 0)
    descartados = resumo_visao.get("total_descartados", 0)

    itens_boletim_definitivo = destaques
    itens_monitoramento = monitoramento + possiveis

    data_inicio_br = formatar_data_br(boletim.data_inicio)
    data_fim_br = formatar_data_br(boletim.data_fim)

    linhas.append("=" * 80)
    linhas.append(f"PRÉ-BOLETIM INFORMATIVO — {data_inicio_br} a {data_fim_br}")
    linhas.append("=" * 80)
    linhas.append("")

    if destaques > 0:
        linhas.append("Resumo do período:")
        linhas.append(
            f"Foram identificada(s) {destaques} publicação(ões) com potencial "
            "de destaque para o boletim definitivo."
        )
    else:
        linhas.append("Resumo do período:")
        linhas.append("Não foram identificadas publicações com impacto direto confirmado para Leroy.")

    linhas.append("")
    linhas.append("Resultado da curadoria:")
    linhas.append(f"- Itens para boletim definitivo: {itens_boletim_definitivo}")
    linhas.append(f"- Itens para monitoramento: {itens_monitoramento}")
    linhas.append(f"- Itens descartados: {descartados}")
    linhas.append("")

    linhas.append("Decisão sugerida:")

    if destaques > 0:
        linhas.append(
            "Gerar boletim definitivo considerando os destaques identificados, "
            "após validação humana."
        )
    else:
        linhas.append(
            "Não gerar boletim definitivo para este período, salvo se algum item "
            "de monitoramento for validado manualmente."
        )

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("PUBLICAÇÕES PARA VALIDAÇÃO")
    linhas.append("-" * 80)
    linhas.append("")

    ordem_visao = {
        VISAO_DESTAQUE_EXECUTIVO: 1,
        VISAO_POSSIVEL_DESTAQUE_REVISAO: 2,
        VISAO_MONITORAMENTO: 3,
        VISAO_REVISAO_HUMANA: 4,
        VISAO_DESCARTADO: 5,
    }

    itens_ordenados = sorted(
        boletim.itens_curados,
        key=lambda item: (
            ordem_visao.get(obter_visao_executiva_item(item), 99),
            item.data_publicacao,
            item.titulo,
        ),
    )

    if not itens_ordenados:
        linhas.append("Nenhuma publicação para validação.")
        linhas.append("")
    else:
        for indice, item in enumerate(itens_ordenados, start=1):
            linhas.append(f"{indice}. {item.titulo}")
            linhas.append(f"Órgão: {item.orgao}")
            linhas.append(f"Data: {formatar_data_br(item.data_publicacao)}")
            linhas.append("")

            linhas.append("O que é:")
            linhas.append(obter_o_que_e_item(item))
            linhas.append("")

            linhas.append("Impacto para Leroy:")
            linhas.append(obter_impacto_leroy_item(item))
            linhas.append("")

            linhas.append("Decisão sugerida:")
            linhas.append(obter_decisao_sugerida_item(item))
            linhas.append("")

            linhas.append("Título original:")
            linhas.append(item.titulo or "Título não disponível.")
            linhas.append("")

            linhas.append("Palavras-chave do match:")
            linhas.extend(formatar_palavras_chave_match_item(item))
            linhas.append("")

            linhas.append("Trechos relevantes:")
            linhas.extend(formatar_trechos_relevantes_item(item))
            linhas.append("")

            linhas.append("Link:")
            linhas.append(item.url or "Link não disponível.")
            linhas.append("")

            if indice < len(itens_ordenados):
                linhas.append("-" * 80)
                linhas.append("")

    linhas.append("=" * 80)
    linhas.append("FIM DO PRÉ-BOLETIM")
    linhas.append("=" * 80)

    return "\n".join(linhas)


# ============================================================
# DIAGNÓSTICO RÁPIDO
# ============================================================

def diagnosticar_pre_boletim(
    boletim: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Gera diagnóstico resumido de um boletim já serializado.
    """
    itens = boletim.get("itens_curados", [])

    por_relevancia = Counter(
        item.get("nivel_relevancia", "")
        for item in itens
    )

    por_classificacao = Counter(
        item.get("classificacao_relacao", "")
        for item in itens
    )

    por_secao = Counter(
        item.get("secao_boletim", "")
        for item in itens
    )

    por_visao_executiva = Counter(
        (item.get("metadados") or {}).get("visao_executiva", "")
        for item in itens
    )

    return {
        "total_itens": len(itens),
        "por_relevancia": dict(por_relevancia),
        "por_classificacao": dict(por_classificacao),
        "por_secao": dict(por_secao),
        "por_visao_executiva": dict(por_visao_executiva),
    }