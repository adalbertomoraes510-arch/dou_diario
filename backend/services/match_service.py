# ============================================================
# SERVICE — Match DOU
# Motor determinístico de palavras-chave, números e processos
# Parametrizado por finalidade
# Com exclusão por título, resgate por relevância forte, match executivo direto, monitoramento setorial V8 e trava administrativa V9 calibrada
# ============================================================

import re
import json
import unicodedata
import time
import datetime
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]

DEFAULT_FINALIDADE_CONFIG = "dou_diario"
DEFAULT_MODELO_PLANILHA = "dou_legacy_v1"

FINALIDADES_DIR = ROOT_DIR / "backend" / "config" / "finalidades"
DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"
MATCH_BASE_DIR = DATA_DOU_DIR / "match"


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar(txt: str) -> str:
    if not txt:
        return ""

    txt = unicodedata.normalize("NFKD", str(txt))
    txt = txt.encode("ASCII", "ignore").decode("ASCII")
    txt = txt.lower()
    txt = re.sub(r"[^\w\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt)

    return txt.strip()


def normalizar_numeros(txt) -> str:
    if txt is None:
        return ""

    txt = str(txt).strip()

    try:
        if float(txt).is_integer():
            txt = str(int(float(txt)))
    except Exception:
        pass

    return re.sub(r"\D", "", txt)


def eh_somente_numero(txt: str) -> bool:
    if not txt:
        return False

    return bool(re.fullmatch(r"[\d\.\-/]+", str(txt).strip()))


def classificar_termo_numerico(termo: str) -> str:
    termo = str(termo)

    tem_letra = bool(re.search(r"[a-zA-Z]", termo))
    tem_numero = bool(re.search(r"\d", termo))

    if tem_letra and tem_numero:
        return "hibrido"

    if tem_numero:
        return "numero"

    return "texto"


def quebrar_termo_em_tokens(termo: str) -> list[str]:
    termo_norm = normalizar(termo)
    return termo_norm.split() if termo_norm else []


# ============================================================
# CONFIGURAÇÃO DE FINALIDADE
# ============================================================

def carregar_json_config(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8-sig"))


def obter_pasta_finalidade(finalidade_config: str) -> Path:
    return FINALIDADES_DIR / finalidade_config


def carregar_config_finalidade(finalidade_config: str) -> dict:
    pasta = obter_pasta_finalidade(finalidade_config)
    caminho_config = pasta / "config.json"

    if not pasta.exists():
        raise FileNotFoundError(
            f"Pasta da finalidade não encontrada: {pasta}"
        )

    if not caminho_config.exists():
        raise FileNotFoundError(
            f"config.json da finalidade não encontrado: {caminho_config}"
        )

    config = carregar_json_config(caminho_config)

    if "modelo_planilha" not in config:
        config["modelo_planilha"] = DEFAULT_MODELO_PLANILHA

    if "arquivo_palavras_chave" not in config:
        config["arquivo_palavras_chave"] = "palavras_chave.xlsx"

    if "arquivo_exclusoes" not in config:
        config["arquivo_exclusoes"] = "exclusoes.xlsx"

    if "arquivo_resgates" not in config:
        config["arquivo_resgates"] = "resgates.xlsx"

    return config


def obter_caminhos_config(finalidade_config: str) -> dict:
    pasta = obter_pasta_finalidade(finalidade_config)
    config = carregar_config_finalidade(finalidade_config)

    palavras_excel = pasta / config.get("arquivo_palavras_chave")
    exclusoes_excel = pasta / config.get("arquivo_exclusoes")
    resgates_excel = pasta / config.get("arquivo_resgates")

    return {
        "finalidade_config": finalidade_config,
        "pasta_config": pasta,
        "config": config,
        "modelo_planilha": config.get("modelo_planilha"),
        "palavras_excel": palavras_excel,
        "exclusoes_excel": exclusoes_excel,
        "resgates_excel": resgates_excel,
    }


def validar_arquivos_config(caminhos: dict) -> None:
    pasta_config = caminhos["pasta_config"]
    palavras_excel = caminhos["palavras_excel"]

    if not pasta_config.exists():
        raise FileNotFoundError(
            f"Pasta de configuração não encontrada: {pasta_config}"
        )

    if not palavras_excel.exists():
        raise FileNotFoundError(
            f"Arquivo de palavras-chave não encontrado: {palavras_excel}"
        )


# ============================================================
# CLASSIFICAÇÃO AUTOMÁTICA — MODELO SIMPLES
# ============================================================

TERMOS_EMPRESA = {
    "leroy",
    "leroy merlin",
    "leroy merlin brasil",
    "leroy merlin companhia brasileira",
    "merlin",
}

TERMOS_REGULATORIOS = {
    "inmetro",
    "anvisa",
    "ibama",
    "mapa",
    "cetesb",
    "crea",
    "cadri",
    "avcb",
    "abnt",
    "nbr",
    "rohs",
    "certificacao",
    "certificado",
    "conformidade",
    "homologacao",
    "registro",
    "licenciamento",
    "autorizacao",
    "validacao",
    "norma tecnica",
    "importacao",
    "exportacao",
    "comercializacao",
    "distribuicao",
    "fabricacao",
    "fornecedor",
    "processo",
    "protocolo",
    "requerimento",
    "deferido",
    "indeferido",
    "suspensao",
    "cancelamento",
    "regularizacao",
    "fispq",
    "rapp",
    "rotulagem",
    "etiquetagem",
}

TERMOS_PROCESSO = {
    "processo",
    "protocolo",
    "requerimento",
    "deferido",
    "indeferido",
}

TERMOS_TECNICOS = {
    "fispq",
    "rapp",
    "rotulagem",
    "etiquetagem",
    "norma tecnica",
    "abnt",
    "nbr",
    "certificacao",
    "certificado",
    "conformidade",
    "homologacao",
    "licenciamento",
    "autorizacao",
    "validacao",
    "registro",
}

# Termos administrativos/fracos: podem ser úteis para auditoria, mas NÃO
# sustentam relevância sozinhos na finalidade informativos.
TERMOS_FRACOS_CONTEXTO = {
    "processo",
    "protocolo",
    "requerimento",
    "deferido",
    "indeferido",
    "registro",
    "autorizacao",
    "homologacao",
    "validacao",
    "licenciamento",
    "fornecedor",
    "comercializacao",
    "distribuicao",
    "fabricacao",
    "fiscalizacao",
    "notificacao",
    "conformidade",
    "certificado",
    "certidao",
    "credenciamento",
    "habilitacao",
}

# Termos de produto/assunto muito genéricos no DOU.
# Eles podem continuar na planilha, mas não contam como produto específico
# para validar contexto quando aparecem sem empresa/órgão/evento forte.
TERMOS_PRODUTO_GENERICOS = {
    # Termos observados no DOU com alto risco de falso positivo.
    # Eles podem ser relevantes quando houver empresa ou contexto regulatório forte,
    # mas NÃO devem sustentar match executivo sozinhos.
    "base",
    "energia",
    "extensao",
    "serra",
    "bloco",
    "piso",
    "concreto",
    "gas",
    "irrigacao",
    "conexao",
    "incendio",
    "quimico",
    "tomada",
    "glp",
    "cabo",
    "barra",
    "porta",
    "janela",
    "madeira",
    "ferro",
    "aco",
    "tubo",
    "tinta",
    "argamassa",
    "cimento",
    "areia",
    "pedra",
    "mangueira",
    "gesso",
    "bateria",
    "gerador",
    "fogao",
    "compressor",
    "carregador",
    "ventilador",
    "cola",
    "silicone",
    "adubo",
    "acido",
    "litio",
    "solar",
    "telha",
    "adesivo",
}

# Termos setoriais regulatórios: indicam assunto de interesse regulatório,
# mas sem empresa/razão social/CNPJ não caracterizam relação direta com Leroy.
# Esses termos ajudam a alimentar monitoramento setorial, não match executivo.
TERMOS_SETORIAIS_REGULATORIOS = {
    "toxico",
    "produto toxico",
    "produtos toxicos",
    "quimico",
    "produto quimico",
    "produtos quimicos",
    "agrotoxico",
    "agrotoxicos",
    "saneante",
    "saneantes",
    "domissanitario",
    "domissanitarios",
    "rapp",
    "fispq",
    "rotulagem",
    "etiquetagem",
    "certificacao compulsoria",
    "registro de produto",
}

# V8 — Calibração manual do monitoramento setorial.
# A triagem dos 17 monitoramentos e dos 6 remanescentes mostrou que
# nem todo órgão + evento sem empresa deve aparecer no relatório.
# Estes conjuntos deixam no monitoramento apenas os cenários setoriais
# úteis para Leroy/produtos e rebaixam ruídos sanitários/farmacêuticos.
TERMOS_ORGAOS_MONITORAMENTO_AMBIENTAL_PRODUTO = {
    "ibama",
    "mapa",
    "ministerio da agricultura",
    "ministerio da agricultura e pecuaria",
}

TERMOS_ORGAOS_MONITORAMENTO_COMEX = {
    "receita federal",
    "secretaria da receita federal",
    "secretaria especial da receita federal",
}

TERMOS_ORGAOS_MONITORAMENTO_SANITARIO = {
    "anvisa",
    "vigilancia sanitaria",
}

TERMOS_ORGAOS_MONITORAMENTO_METROLOGIA = {
    "inmetro",
}

# Órgãos que, sem empresa direta, tendem a gerar ruído para a finalidade Leroy.
TERMOS_ORGAOS_REBAIXAR_SEM_EMPRESA = {
    "crea",
    "anp",
    "aneel",
    "anatel",
}

TERMOS_PRODUTOS_COMERCIALIZAVEIS_MONITORAMENTO = {
    "cola",
    "silicone",
    "adesivo",
    "tinta",
    "argamassa",
    "cimento",
    "saneante",
    "saneantes",
    "domissanitario",
    "domissanitarios",
    "quimico",
    "produto quimico",
    "produtos quimicos",
    "acido",
    "litio",
    "rotulagem",
    "etiquetagem",
}

TERMOS_EVENTOS_MONITORAMENTO_FORTE = {
    "auto de infracao",
    "autuacao",
    "apreensao",
    "interdicao",
    "cancelamento",
    "suspensao",
    "proibicao",
    "multa",
    "irregularidade",
}

TERMOS_ATIVIDADES_COMEX = {
    "importacao",
    "exportacao",
}

TERMOS_ATIVIDADES_PRODUTO_REGULADO = {
    "comercializacao",
    "distribuicao",
    "fabricacao",
    "importacao",
    "exportacao",
    "fiscalizacao",
}

# Termos que, quando aparecem em contexto ANVISA/Vigilância sem empresa,
# indicam escopo hospitalar/farmacêutico/biológico fora da finalidade Leroy.
TERMOS_SANITARIOS_REBAIXAR_SEM_EMPRESA = {
    "produto biologico",
    "produtos biologicos",
    "biologico",
    "biologicos",
    "radiofarmaco",
    "radiofarmacos",
    "sangue",
    "tecido",
    "tecidos",
    "celula",
    "celulas",
    "orgao",
    "orgaos",
    "terapia avancada",
    "terapias avancadas",
    "produtos de terapia avancada",
    "medicamento",
    "medicamentos",
    "farmaco",
    "farmacos",
    "farmaceutico",
    "farmaceuticos",
    "produto biologico radiofarmaco sangue tecido celula orgao",
}

# Expressões de autorização/cancelamento sanitário genérico que só entram se
# houver produto/tema regulado aderente à finalidade.
TERMOS_SANITARIOS_GENERICOS_SEM_PRODUTO = {
    "autorizacao de funcionamento",
    "autorizacao de funcionamento de empresas",
    "afe",
    "coordenacao de autorizacao de funcionamento de empresas",
}

# V9 — Contextos administrativos, judiciários, militares e seletivos.
# Não são bloqueados cegamente: só rebaixam quando NÃO há empresa,
# NÃO há órgão regulador real e NÃO há tema regulatório setorial útil.
TERMOS_CONTEXTO_ADMINISTRATIVO_V9 = {
    "ministerio da defesa",
    "comando da marinha",
    "marinha",
    "diretoria geral do pessoal da marinha",
    "diretoria de ensino",
    "servico de selecao",
    "servico de selecao do pessoal",
    "exercito",
    "comando do exercito",
    "aeronautica",
    "forca aerea",
    "poder judiciario",
    "tribunal",
    "tribunal regional do trabalho",
    "trt",
    "justica do trabalho",
    "tribunal de justica",
    "tribunal regional federal",
    "ministerio publico",
    "universidade",
    "universidade federal",
    "instituto federal",
    "prefeitura",
    "camara municipal",
}

TERMOS_TITULO_ADMINISTRATIVO_V9 = {
    "edital de abertura",
    "edital de convocacao",
    "processo seletivo",
    "concurso",
    "concurso publico",
    "servico de selecao",
    "resultado final",
    "homologacao de concurso",
    "selecao publica",
}

# Órgãos/agentes reguladores fortes.
# V3: empresa + órgão regulador é match forte.
TERMOS_ORGAOS_REGULADORES_FORTES = {
    "inmetro",
    "anvisa",
    "ibama",
    "mapa",
    "ministerio da agricultura e pecuaria",
    "ministerio da agricultura",
    "cetesb",
    "crea",
    "cadri",
    "avcb",
    "anatel",
    "aneel",
    "anp",
    "receita federal",
    "secretaria da receita federal",
    "secretaria especial da receita federal",
    "vigilancia sanitaria",
    "procon",
    "conama",
    "abnt",
}

# Termos técnicos/regulatórios fortes, mas que não são exatamente órgãos.
TERMOS_TECNICOS_REGULATORIOS_FORTES = {
    "nbr",
    "rohs",
    "fispq",
    "rapp",
    "rotulagem",
    "etiquetagem",
    "norma tecnica",
    "certificacao",
    "certificacao compulsoria",
    "regulamento tecnico",
}

TERMOS_CONTEXTO_REGULATORIO_FORTE = (
    TERMOS_ORGAOS_REGULADORES_FORTES
    | TERMOS_TECNICOS_REGULATORIOS_FORTES
)

# V3: atos normativos. Empresa + lei/decreto/portaria/resolução etc.
# deve ser match forte, mesmo sem produto específico.
TERMOS_ATO_NORMATIVO = {
    "lei",
    "decreto",
    "portaria",
    "resolucao",
    "instrucao normativa",
    "consulta publica",
    "ato",
    "despacho",
    "rdc",
    "norma",
    "norma tecnica",
    "regulamento",
    "regulamento tecnico",
    "deliberacao",
    "circular",
    "instrucao",
    "comunicado",
    "edital de consulta publica",
}

# Eventos materiais têm maior peso: indicam risco, restrição,
# autuação, retirada, suspensão ou regularização material.
TERMOS_EVENTO_MATERIAL = {
    # Eventos materiais reais: indicam risco, restrição, penalidade,
    # retirada, bloqueio ou alteração de situação regulatória.
    "auto de infracao",
    "autuacao",
    "multa",
    "notificacao de multa",
    "apreensao",
    "interdicao",
    "irregularidade",
    "infracao sanitaria",
    "risco sanitario",
    "produto apreendido",
    "produto cancelado",
    "produto interditado",
    "produto irregular",
    "produto proibido",
    "produto suspenso",
    "recolhimento",
    "recall",
    "cancelamento",
    "suspensao",
    "regularizacao",
    "proibicao",
}

# Atividades regulatórias/comerciais: importantes para contexto,
# mas muito genéricas para serem tratadas como evento material.
TERMOS_ATIVIDADE_REGULATORIA = {
    "importacao",
    "exportacao",
    "comercializacao",
    "distribuicao",
    "fabricacao",
    "fiscalizacao",
}

# Termos que podem resgatar publicação bloqueada por título genérico
# quando a finalidade usa filtro contextual conservador.
# Ex.: EXTRATO/LICITAÇÃO só volta se houver empresa ou evento material forte.
TERMOS_RESGATE_AUTONOMO = {
    "leroy",
    "leroy merlin",
    "leroy merlin brasil",
    "leroy merlin companhia brasileira",
    "auto de infracao",
    "autuacao",
    "apreensao",
    "interdicao",
    "irregularidade",
    "produto apreendido",
    "produto cancelado",
    "produto interditado",
    "produto irregular",
    "produto proibido",
    "produto suspenso",
    "recolhimento",
    "recall",
}


def classificar_categoria_termo(termo: str) -> str:
    termo_norm = normalizar(termo)

    if termo_norm in TERMOS_EMPRESA:
        return "empresa"

    if termo_norm in TERMOS_ORGAOS_REGULADORES_FORTES:
        return "orgao_regulador"

    if termo_norm in TERMOS_ATO_NORMATIVO:
        return "ato_normativo"

    if termo_norm in TERMOS_EVENTO_MATERIAL:
        return "evento_material"

    if termo_norm in TERMOS_ATIVIDADE_REGULATORIA:
        return "atividade_regulatoria"

    if termo_norm in TERMOS_PROCESSO:
        return "processo"

    if termo_norm in TERMOS_FRACOS_CONTEXTO:
        return "termo_fraco"

    if termo_norm in TERMOS_TECNICOS_REGULATORIOS_FORTES:
        return "tecnico_forte"

    if termo_norm in TERMOS_TECNICOS:
        return "tecnico"

    if termo_norm in TERMOS_REGULATORIOS:
        return "regulatorio"

    if termo_norm in TERMOS_SETORIAIS_REGULATORIOS:
        return "setorial_regulatorio"

    if termo_norm in TERMOS_PRODUTO_GENERICOS:
        return "produto_generico"

    return "produto_ou_termo"


# ============================================================
# LEITURA DE PLANILHAS SIMPLES
# ============================================================

def carregar_coluna_unica_excel(caminho: Path) -> list[str]:
    if not caminho.exists():
        return []

    xls = pd.ExcelFile(caminho)
    primeira_aba = xls.sheet_names[0]

    df = pd.read_excel(
        caminho,
        sheet_name=primeira_aba,
        header=None,
        dtype=str
    ).fillna("")

    termos = set()

    for valor in df.iloc[:, 0]:
        valor = str(valor).strip()

        if valor:
            termos.add(normalizar(valor))

    return sorted(termos)


# ============================================================
# CARGA DE CONFIGURAÇÕES — MODELO LEGADO DOU
# ============================================================

def carregar_palavras_chave_dou_legacy(
    palavras_excel: Path
) -> tuple[list[dict], list[str]]:
    palavras_textuais = set()
    processos_busca = []

    df_mono = pd.read_excel(
        palavras_excel,
        sheet_name="MONOGRAFIAS APROVADAS ANVISA",
        header=0,
        dtype=str
    ).fillna("")

    col_mono = df_mono.columns[0]

    for valor in df_mono[col_mono]:
        valor = str(valor).strip()

        if valor:
            # Para monografias, o código administrativo da planilha não deve
            # fazer parte da palavra-chave operacional.
            # Exemplos:
            # - "17 – Metomil" vira "Metomil"
            # - "A02 - Acefato" vira "Acefato"
            # - "D27 - 2,4-D" vira "2,4-D"
            #
            # Isso mantém MONOGRAFIAS APROVADAS ANVISA como origem válida,
            # mas impede que códigos como 17, A02, D27 etc. sustentem match
            # ou apareçam no relatório/e-mail como palavra-chave.
            valor_monografia = extrair_nome_monografia_legacy(valor)

            if valor_monografia:
                palavras_textuais.add((
                    valor_monografia,
                    normalizar(valor_monografia),
                    "MONOGRAFIAS APROVADAS ANVISA",
                    str(col_mono).strip(),
                ))

    df_proc = pd.read_excel(
        palavras_excel,
        sheet_name="PROCESSOS",
        header=0,
        dtype=str
    ).fillna("")

    df_proc.columns = (
        df_proc.columns
        .astype(str)
        .str.strip()
        .str.replace("\u00a0", " ", regex=False)
        .str.upper()
    )

    if "PROCESSO" not in df_proc.columns:
        raise RuntimeError("Coluna 'PROCESSO' não encontrada na aba PROCESSOS")

    colunas_textuais = (
        "NOME DA EMPRESA",
        "NOME DO PRODUTO",
        "CATEGORIA",
    )

    for col in colunas_textuais:
        if col in df_proc.columns:
            for valor in df_proc[col]:
                valor = str(valor).strip()

                if valor:
                    palavras_textuais.add((
                        valor,
                        normalizar(valor),
                        "PROCESSOS",
                        col,
                    ))

    for valor in df_proc["PROCESSO"]:
        valor = str(valor).strip()

        if valor:
            processos_busca.append(valor)

    palavras_formatadas = []

    for original, normalizado, origem_aba, origem_coluna in sorted(palavras_textuais):
        palavras_formatadas.append({
            "original": original,
            "normalizado": normalizado,
            "tipo": classificar_termo_numerico(original),
            "categoria": "legado",
            "origem_aba": origem_aba,
            "origem_coluna": origem_coluna,
        })

    return palavras_formatadas, sorted(set(processos_busca))


# ============================================================
# CARGA DE CONFIGURAÇÕES — MODELO SIMPLES
# ============================================================

def carregar_palavras_chave_simples_coluna_unica(
    palavras_excel: Path
) -> tuple[list[dict], list[str]]:
    termos = carregar_coluna_unica_excel(palavras_excel)

    palavras_formatadas = []
    processos_busca = []

    for termo_norm in termos:
        categoria = classificar_categoria_termo(termo_norm)
        tipo = classificar_termo_numerico(termo_norm)

        palavras_formatadas.append({
            "original": termo_norm.upper(),
            "normalizado": termo_norm,
            "tipo": tipo,
            "categoria": categoria,
        })

    return palavras_formatadas, processos_busca


def carregar_palavras_chave(
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG
) -> tuple[list[dict], list[str], dict]:
    caminhos = obter_caminhos_config(finalidade_config)
    validar_arquivos_config(caminhos)

    modelo = caminhos["modelo_planilha"]
    palavras_excel = caminhos["palavras_excel"]

    if modelo == "simples_coluna_unica_v1":
        palavras, processos = carregar_palavras_chave_simples_coluna_unica(
            palavras_excel
        )

    elif modelo == "dou_legacy_v1":
        palavras, processos = carregar_palavras_chave_dou_legacy(
            palavras_excel
        )

    else:
        raise RuntimeError(
            f"Modelo de planilha não suportado: {modelo}"
        )

    return palavras, processos, caminhos


def carregar_exclusoes(
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG
) -> list[str]:
    caminhos = obter_caminhos_config(finalidade_config)
    exclusoes_excel = caminhos["exclusoes_excel"]

    if not exclusoes_excel.exists():
        print(f"[AVISO] Arquivo de exclusões não encontrado: {exclusoes_excel}")
        return []

    return carregar_coluna_unica_excel(exclusoes_excel)


def carregar_resgates(
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG
) -> list[str]:
    caminhos = obter_caminhos_config(finalidade_config)
    resgates_excel = caminhos["resgates_excel"]

    if not resgates_excel.exists():
        print(f"[AVISO] Arquivo de resgates não encontrado: {resgates_excel}")
        return []

    return carregar_coluna_unica_excel(resgates_excel)


# ============================================================
# REGRAS DE EXCLUSÃO E RESGATE
# ============================================================

def match_parcial_excluido(token_match: str, termos_exclusao: list[str]) -> bool:
    if not token_match or not termos_exclusao:
        return False

    token_norm = normalizar(token_match)

    return token_norm in termos_exclusao


def montar_texto_resgate(registro: dict) -> str:
    partes = [
        registro.get("titulo") or "",
        registro.get("titulo_publicacao") or "",
        registro.get("orgao") or "",
        registro.get("orgao_publicacao") or "",
        registro.get("texto_integral") or "",
        registro.get("texto_normalizado") or "",
    ]

    return normalizar(" ".join(str(p) for p in partes if p))


def termo_exato_no_texto(texto_normalizado: str, termo_normalizado: str) -> bool:
    if not texto_normalizado or not termo_normalizado:
        return False

    # Evita falso positivo por substring.
    # Exemplo real do teste: "mapa" não pode bater dentro de "amapa".
    padrao = rf"(?<!\w){re.escape(termo_normalizado)}(?!\w)"

    return bool(re.search(padrao, texto_normalizado))


def buscar_termo_em_texto(
    texto_normalizado: str,
    termos: list[str]
) -> tuple[bool, str | None]:
    if not texto_normalizado or not termos:
        return False, None

    texto_norm = normalizar(texto_normalizado)

    for termo in termos:
        termo_norm = normalizar(termo)

        if not termo_norm:
            continue

        if termo_exato_no_texto(texto_norm, termo_norm):
            return True, termo

    return False, None


def publicacao_bloqueada_por_exclusao(
    registro: dict,
    termos_exclusao: list[str]
) -> tuple[bool, str | None]:
    if not termos_exclusao:
        return False, None

    titulo = normalizar(registro.get("titulo") or "")
    titulo_publicacao = normalizar(registro.get("titulo_publicacao") or "")
    texto_titulo = " ".join(
        parte for parte in [titulo, titulo_publicacao]
        if parte
    )

    if not texto_titulo:
        return False, None

    return buscar_termo_em_texto(
        texto_normalizado=texto_titulo,
        termos=termos_exclusao
    )


def montar_texto_match_publicacao(
    registro: dict,
    modelo_planilha: str = DEFAULT_MODELO_PLANILHA,
) -> str:
    """
    Monta o texto usado pelo motor de match.

    Regra de segurança:
    - Para modelos diferentes de dou_legacy_v1, mantém exatamente a lógica anterior:
      texto_integral ou texto_normalizado.
    - Para dou_legacy_v1, amplia a busca para campos textuais estruturais já
      presentes na publicação/base, incluindo texto/blocos/ementa/conteúdo.

    Objetivo:
    - Permitir que processos cadastrados na aba PROCESSOS sejam efetivamente
      registrados em matchs/matchs_detectados quando aparecem na publicação.
    - Não altera score contextual, regras do informativos ou estrutura de saída.
    """
    if modelo_planilha != "dou_legacy_v1":
        return (
            registro.get("texto_integral")
            or registro.get("texto_normalizado")
            or ""
        )

    partes = [
        registro.get("titulo") or "",
        registro.get("titulo_publicacao") or "",
        registro.get("orgao") or "",
        registro.get("orgao_publicacao") or "",
        registro.get("texto_integral") or "",
        registro.get("texto_normalizado") or "",
        registro.get("texto") or "",
        registro.get("conteudo") or "",
        registro.get("texto_publicacao") or "",
        registro.get("resumo") or "",
        registro.get("descricao") or "",
        registro.get("ementa") or "",
    ]

    for chave in ("blocos", "trechos", "itens", "publicacao"):
        valor = registro.get(chave)

        if valor in [None, "", [], {}]:
            continue

        try:
            partes.append(json.dumps(valor, ensure_ascii=False))
        except Exception:
            partes.append(str(valor))

    return "\n".join(str(parte) for parte in partes if parte)



def publicacao_resgatada_por_relevancia(
    registro: dict,
    termos_resgate: list[str],
    modo_conservador: bool = False,
) -> tuple[bool, str | None]:
    if not termos_resgate:
        return False, None

    termos_para_busca = termos_resgate

    if modo_conservador:
        # Na finalidade informativos, o resgate é conservador: só termos
        # fortes/empresa podem derrubar uma exclusão de título. Isso evita
        # que EXTRATO/LICITAÇÃO volte apenas por conter "fiscalização",
        # "mapa", "inmetro" etc.
        termos_para_busca = [
            termo for termo in termos_resgate
            if normalizar(termo) in TERMOS_RESGATE_AUTONOMO
        ]

    if not termos_para_busca:
        return False, None

    texto_resgate = montar_texto_resgate(registro)

    return buscar_termo_em_texto(
        texto_normalizado=texto_resgate,
        termos=termos_para_busca
    )


# ============================================================
# REGRAS DE MATCH
# ============================================================

def contem_palavra(
    texto: str,
    palavras_textuais: list[dict],
    termos_exclusao: list[str]
) -> list[dict]:

    encontrados = []

    if not texto or not palavras_textuais:
        return encontrados

    texto_norm = normalizar(texto)

    for termo_obj in palavras_textuais:
        termo_original = termo_obj.get("original", "")
        termo_norm = termo_obj.get("normalizado", "")

        if not termo_norm:
            continue

        match = re.search(rf"\b{re.escape(termo_norm)}\b", texto_norm)

        if not match:
            continue

        trecho_encontrado = match.group(0)

        if match_parcial_excluido(trecho_encontrado, termos_exclusao):
            continue

        encontrados.append({
            "termo": termo_original,
            "tipo": "match_direto",
            "categoria": termo_obj.get("categoria"),
            "encontrados": [trecho_encontrado],
            "origem_aba": termo_obj.get("origem_aba"),
            "origem_coluna": termo_obj.get("origem_coluna"),
        })

    return encontrados


def contem_processo(texto: str, processos: list[str]) -> list[dict]:
    encontrados = []

    if not texto or not processos:
        return encontrados

    texto_digits = normalizar_numeros(texto)

    for processo in processos:
        processo_original = str(processo).strip()

        if not processo_original:
            continue

        processo_digits = normalizar_numeros(processo_original)

        if not processo_digits:
            continue

        if processo_digits in texto_digits:
            encontrados.append({
                "termo": processo_original,
                "tipo": "match_processo",
                "categoria": "processo",
                "encontrados": [processo_original],
            })

    return encontrados


def termo_eh_produto_legacy(termo_obj: dict | None) -> bool:
    """Identifica termos oriundos da coluna NOME DO PRODUTO.

    A categoria continua sendo carregada normalmente como palavra-chave.
    Esta função é usada somente para endurecer a regra de tokenização
    de produto híbrido, evitando falso positivo por tokens soltos.
    """
    if not termo_obj:
        return False

    origem_aba = normalizar(termo_obj.get("origem_aba") or "")
    origem_coluna = normalizar(termo_obj.get("origem_coluna") or "")

    return origem_aba == "processos" and origem_coluna == "nome do produto"


def termo_eh_monografia_legacy(termo_obj: dict | None) -> bool:
    """Identifica termos vindos da aba MONOGRAFIAS APROVADAS ANVISA.

    A aba continua sendo carregada normalmente. A diferença é que termos
    no formato "17 – Metomil" não podem ser validados pelo número/código
    inicial; a validação deve ocorrer pelo nome da monografia.
    """
    if not termo_obj:
        return False

    origem_aba = normalizar(termo_obj.get("origem_aba") or "")

    return origem_aba == "monografias aprovadas anvisa"


def extrair_nome_monografia_legacy(termo: str) -> str:
    """Remove código inicial de monografia e retorna o nome pesquisável.

    Exemplos:
    - "17 – Metomil" => "Metomil"
    - "F46 - Flumioxazina" => "Flumioxazina"
    - "D27 - 2,4-D" => "2,4-D"

    O código antes do hífen/travessão é identificador da planilha, não prova
    de ocorrência no DOU. Por isso ele não pode sustentar match sozinho.
    """
    termo_limpo = str(termo or "").strip()

    if not termo_limpo:
        return ""

    # Remove prefixos como "17 -", "17 –", "F46 -", "D27 -".
    termo_sem_codigo = re.sub(
        r"^\s*[A-Za-z]?\d+\s*[-–—]\s*",
        "",
        termo_limpo,
    ).strip()

    return termo_sem_codigo or termo_limpo


def match_monografia_legacy(termo: str, texto: str) -> bool:
    """Valida monografia pelo nome químico, nunca pelo código inicial.

    Antes, "17 – Metomil" podia passar pela regra híbrida legada usando
    tokens fracos do identificador. Agora, para monografias, o match só é
    aceito se o nome extraído após o código aparecer como termo exato no texto.
    """
    nome_monografia = extrair_nome_monografia_legacy(termo)
    nome_norm = normalizar(nome_monografia)
    texto_norm = normalizar(texto)

    if not nome_norm or not texto_norm:
        return False

    return termo_exato_no_texto(texto_norm, nome_norm)


def tokens_relevantes_produto_hibrido(tokens: list[str]) -> list[str]:
    """Remove tokens fracos de produto híbrido.

    Exemplo: FLUMIOXAZINA 500 WP BRILLIANCE
    - tokens fracos: 500, WP
    - tokens relevantes: FLUMIOXAZINA, BRILLIANCE

    Tokens numéricos ou muito curtos não podem sustentar match por proximidade.
    Eles continuam válidos quando a expressão completa do produto aparece no texto.
    """
    relevantes = []

    for token in tokens:
        token_norm = normalizar(token)

        if not token_norm:
            continue

        if token_norm.isdigit():
            continue

        if len(token_norm) < 4:
            continue

        if token_norm not in relevantes:
            relevantes.append(token_norm)

    return relevantes


def tokens_do_texto_normalizado(texto_norm: str) -> list[str]:
    return texto_norm.split() if texto_norm else []


def produto_hibrido_por_tokens_proximos(
    termo: str,
    texto: str,
    distancia_maxima_tokens: int = 12,
) -> bool:
    """Valida produto híbrido por expressão completa ou tokens fortes próximos.

    Essa regra substitui o comportamento antigo para NOME DO PRODUTO, que
    aceitava todos os tokens espalhados em qualquer ponto do texto.

    Regras:
    1) Se a expressão completa do produto aparece, é match.
    2) Caso contrário, exige pelo menos dois tokens relevantes, não numéricos
       e com 4+ caracteres, encontrados próximos no texto.
    3) Tokens curtos/numéricos como 500, WP, SC, WG, BR não validam o match
       quando aparecem isolados ou espalhados.
    """
    termo_norm = normalizar(termo)
    texto_norm = normalizar(texto)

    if not termo_norm or not texto_norm:
        return False

    if termo_exato_no_texto(texto_norm, termo_norm):
        return True

    tokens_relevantes = tokens_relevantes_produto_hibrido(
        quebrar_termo_em_tokens(termo)
    )

    if len(tokens_relevantes) < 2:
        return False

    texto_tokens = tokens_do_texto_normalizado(texto_norm)

    if not texto_tokens:
        return False

    posicoes_por_token: dict[str, list[int]] = {
        token: [] for token in tokens_relevantes
    }

    for idx, token_texto in enumerate(texto_tokens):
        if token_texto in posicoes_por_token:
            posicoes_por_token[token_texto].append(idx)

    if any(not posicoes for posicoes in posicoes_por_token.values()):
        return False

    todas_posicoes = [
        posicao
        for posicoes in posicoes_por_token.values()
        for posicao in posicoes
    ]

    for ancora in todas_posicoes:
        if all(
            any(abs(posicao - ancora) <= distancia_maxima_tokens for posicao in posicoes)
            for posicoes in posicoes_por_token.values()
        ):
            return True

    return False


def match_hibrido_estruturado(
    termo: str,
    texto: str,
    termo_obj: dict | None = None,
) -> bool:
    if not termo or not texto:
        return False

    if termo_eh_produto_legacy(termo_obj):
        return produto_hibrido_por_tokens_proximos(
            termo=termo,
            texto=texto,
        )

    if termo_eh_monografia_legacy(termo_obj):
        return match_monografia_legacy(
            termo=termo,
            texto=texto,
        )

    texto_norm = normalizar(texto)
    tokens = quebrar_termo_em_tokens(termo)

    if not tokens:
        return False

    # Regra legada preservada para termos híbridos que não vieram de
    # NOME DO PRODUTO nem de MONOGRAFIAS APROVADAS ANVISA.
    for token in tokens:
        if token not in texto_norm:
            return False

    return True


def contem_numeros_substring(
    texto: str,
    termos: list[dict],
    contexto_log: dict | None = None,
) -> list[dict]:

    encontrados = []

    if not texto or not termos:
        return encontrados

    inicio_funcao = time.perf_counter()
    total_termos = len(termos)
    tipo_log = (contexto_log or {}).get("tipo", "NUMERO/HIBRIDO")
    pub_atual = (contexto_log or {}).get("pub_atual")
    pub_total = (contexto_log or {}).get("pub_total")

    texto_digits = normalizar_numeros(texto)
    texto_norm = normalizar(texto)

    for idx_termo, termo_obj in enumerate(termos, start=1):
        termo_original = str(termo_obj.get("original", "")).strip()

        if contexto_log and (
            idx_termo == 1
            or idx_termo % LOG_MATCH_HIBRIDO_A_CADA == 0
            or idx_termo == total_termos
        ):
            tempo_decorrido = time.perf_counter() - inicio_funcao
            _log_match(
                f"[MATCH][{tipo_log}] pub={pub_atual}/{pub_total} | "
                f"termo={idx_termo}/{total_termos} | "
                f"tempo={tempo_decorrido:.1f}s | "
                f"termo_atual={termo_original[:80]}"
            )

        if not termo_original:
            continue

        if eh_somente_numero(termo_original):
            termo_digits = normalizar_numeros(termo_original)

            if termo_digits and termo_digits in texto_digits:
                encontrados.append({
                    "termo": termo_original,
                    "tipo": "match_numero",
                    "categoria": termo_obj.get("categoria"),
                    "encontrados": [termo_original],
                    "origem_aba": termo_obj.get("origem_aba"),
                    "origem_coluna": termo_obj.get("origem_coluna"),
                })

        else:
            termo_norm = normalizar(termo_original)

            if match_hibrido_estruturado(
                termo=termo_original,
                texto=texto,
                termo_obj=termo_obj,
            ):
                encontrados.append({
                    "termo": termo_original,
                    "tipo": "match_hibrido",
                    "categoria": termo_obj.get("categoria"),
                    "encontrados": [termo_original],
                    "origem_aba": termo_obj.get("origem_aba"),
                    "origem_coluna": termo_obj.get("origem_coluna"),
                })

            elif re.search(rf"\b{re.escape(termo_norm)}\b", texto_norm):
                encontrados.append({
                    "termo": termo_original,
                    "tipo": "match_texto_hibrido",
                    "categoria": termo_obj.get("categoria"),
                    "encontrados": [termo_original],
                    "origem_aba": termo_obj.get("origem_aba"),
                    "origem_coluna": termo_obj.get("origem_coluna"),
                })

    return encontrados


def consolidar_matches(matches_raw: list[dict]) -> list[dict]:
    vistos = set()
    matches = []

    for match in matches_raw:
        chave = (
            match.get("termo"),
            match.get("tipo"),
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        matches.append(match)

    return matches


# ============================================================
# SCORE CONTEXTUAL — INFORMATIVOS
# ============================================================

def termos_presentes_no_texto(
    texto_normalizado: str,
    termos_referencia: set[str]
) -> set[str]:
    encontrados = set()

    if not texto_normalizado or not termos_referencia:
        return encontrados

    texto_norm = normalizar(texto_normalizado)

    for termo in termos_referencia:
        termo_norm = normalizar(termo)

        if not termo_norm:
            continue

        if termo_exato_no_texto(texto_norm, termo_norm):
            encontrados.add(termo_norm)

    return encontrados


def montar_base_contextual(
    matches: list[dict],
    texto_contexto: str = "",
) -> dict:
    categorias = {
        str(match.get("categoria") or "")
        for match in matches
    }
    categorias.discard("")

    termos_matches = {
        normalizar(match.get("termo") or "")
        for match in matches
        if match.get("termo")
    }
    termos_matches.discard("")

    texto_norm = normalizar(texto_contexto or "")

    termos_empresa = (
        termos_matches.intersection(TERMOS_EMPRESA)
        | termos_presentes_no_texto(texto_norm, TERMOS_EMPRESA)
    )

    termos_orgao_regulador = (
        termos_matches.intersection(TERMOS_ORGAOS_REGULADORES_FORTES)
        | termos_presentes_no_texto(texto_norm, TERMOS_ORGAOS_REGULADORES_FORTES)
    )

    termos_tecnicos_fortes = (
        termos_matches.intersection(TERMOS_TECNICOS_REGULATORIOS_FORTES)
        | termos_presentes_no_texto(texto_norm, TERMOS_TECNICOS_REGULATORIOS_FORTES)
    )

    termos_contexto_regulatorio_forte = (
        termos_orgao_regulador
        | termos_tecnicos_fortes
    )

    termos_ato_normativo = (
        termos_matches.intersection(TERMOS_ATO_NORMATIVO)
        | termos_presentes_no_texto(texto_norm, TERMOS_ATO_NORMATIVO)
    )

    termos_evento_material = (
        termos_matches.intersection(TERMOS_EVENTO_MATERIAL)
        | termos_presentes_no_texto(texto_norm, TERMOS_EVENTO_MATERIAL)
    )

    termos_atividade_regulatoria = (
        termos_matches.intersection(TERMOS_ATIVIDADE_REGULATORIA)
        | termos_presentes_no_texto(texto_norm, TERMOS_ATIVIDADE_REGULATORIA)
    )

    termos_setoriais_regulatorios = (
        termos_matches.intersection(TERMOS_SETORIAIS_REGULATORIOS)
        | termos_presentes_no_texto(texto_norm, TERMOS_SETORIAIS_REGULATORIOS)
    )

    termos_fracos = termos_matches.intersection(TERMOS_FRACOS_CONTEXTO)
    termos_produto_generico = termos_matches.intersection(TERMOS_PRODUTO_GENERICOS)

    termos_produto_especifico = {
        normalizar(match.get("termo") or "")
        for match in matches
        if normalizar(match.get("termo") or "")
        and match.get("categoria") == "produto_ou_termo"
        and normalizar(match.get("termo") or "") not in TERMOS_PRODUTO_GENERICOS
        and normalizar(match.get("termo") or "") not in TERMOS_FRACOS_CONTEXTO
        and normalizar(match.get("termo") or "") not in TERMOS_CONTEXTO_REGULATORIO_FORTE
        and normalizar(match.get("termo") or "") not in TERMOS_ATO_NORMATIVO
        and normalizar(match.get("termo") or "") not in TERMOS_EVENTO_MATERIAL
        and normalizar(match.get("termo") or "") not in TERMOS_PROCESSO
    }

    return {
        "categorias": categorias,
        "termos_matches": termos_matches,
        "termos_empresa": termos_empresa,
        "termos_orgao_regulador": termos_orgao_regulador,
        "termos_tecnicos_fortes": termos_tecnicos_fortes,
        "termos_contexto_regulatorio_forte": termos_contexto_regulatorio_forte,
        "termos_ato_normativo": termos_ato_normativo,
        "termos_evento_material": termos_evento_material,
        "termos_atividade_regulatoria": termos_atividade_regulatoria,
        "termos_setoriais_regulatorios": termos_setoriais_regulatorios,
        "termos_fracos": termos_fracos,
        "termos_produto_generico": termos_produto_generico,
        "termos_produto_especifico": termos_produto_especifico,
        "texto_contexto_normalizado": texto_norm,
    }


def montar_retorno_contextual(
    score: str,
    nivel: int,
    motivo: str,
    base: dict,
    relevante: bool,
) -> dict:
    return {
        "score_contextual": score,
        "nivel_contextual": nivel,
        "motivo_contextual": motivo,
        "categorias_encontradas": sorted(base.get("categorias", [])),
        "termos_empresa": sorted(base.get("termos_empresa", [])),
        "termos_orgao_regulador": sorted(base.get("termos_orgao_regulador", [])),
        "termos_tecnicos_fortes": sorted(base.get("termos_tecnicos_fortes", [])),
        "termos_ato_normativo": sorted(base.get("termos_ato_normativo", [])),
        "termos_evento_material": sorted(base.get("termos_evento_material", [])),
        "termos_atividade_regulatoria": sorted(base.get("termos_atividade_regulatoria", [])),
        "termos_setoriais_regulatorios": sorted(base.get("termos_setoriais_regulatorios", [])),
        "termos_produto_especifico": sorted(base.get("termos_produto_especifico", [])),
        "termos_produto_generico": sorted(base.get("termos_produto_generico", [])),
        "termos_fracos_encontrados": sorted(base.get("termos_fracos", [])),
        "relevante_contextual": relevante,
    }


def contem_algum_termo_v9(texto_normalizado: str, termos: set[str]) -> bool:
    if not texto_normalizado or not termos:
        return False

    for termo in termos:
        termo_norm = normalizar(termo)

        if not termo_norm:
            continue

        if termo_exato_no_texto(texto_normalizado, termo_norm):
            return True

    return False


def deve_rebaixar_contexto_administrativo_v9(base: dict) -> bool:
    """Rebaixa ruídos administrativos/judiciais/militares sem vínculo útil.

    Ex.: Marinha/TRT + ar condicionado/LED + edital administrativo.
    Não bloqueia casos com Leroy, órgão regulador real ou tema setorial forte.
    """

    texto_norm = str(base.get("texto_contexto_normalizado") or "")

    tem_contexto_admin = (
        contem_algum_termo_v9(texto_norm, TERMOS_CONTEXTO_ADMINISTRATIVO_V9)
        or contem_algum_termo_v9(texto_norm, TERMOS_TITULO_ADMINISTRATIVO_V9)
    )

    if not tem_contexto_admin:
        return False

    tem_empresa = bool(base.get("termos_empresa"))
    tem_orgao_regulador_real = bool(base.get("termos_orgao_regulador"))
    # V9.1: não considerar termos técnicos genéricos (ex.: certificação,
    # certificado, conformidade, homologação) como "tema setorial" para
    # salvar contexto administrativo/militar/judicial. No caso Marinha/TRT,
    # esses termos apareciam em edital administrativo e impediam o rebaixamento.
    # Mantém exceção apenas para temas setoriais reais (RAPP, tóxico, FISPQ,
    # rotulagem, saneante, químico etc.).
    temas_setoriais_reais = (
        set(base.get("termos_setoriais_regulatorios", set()))
        | set(base.get("termos_matches", set())).intersection(
            TERMOS_SETORIAIS_REGULATORIOS
        )
    )

    tem_tema_setorial = bool(temas_setoriais_reais)

    if tem_empresa:
        return False

    if tem_orgao_regulador_real:
        return False

    if tem_tema_setorial:
        return False

    return True


def avaliar_monitoramento_setorial_v8(base: dict) -> tuple[bool, str, int]:
    """Decide se um caso sem empresa deve ficar em monitoramento setorial.

    Regra V8 calibrada com a triagem manual dos 17 casos e dos 6 remanescentes de 13/05/2026:
    manter apenas cenários regulatórios setoriais úteis para Leroy/produtos
    e rebaixar ruídos como CREA/CAT, ANP gás/GLP, IBAMA/MAPA genérico,
    Receita Federal sem importação/exportação, ANVISA biológicos/fármacos e
    autorização sanitária genérica sem produto/empresa.
    """

    orgaos = set(base.get("termos_orgao_regulador", set()))
    eventos = set(base.get("termos_evento_material", set()))
    atividades = set(base.get("termos_atividade_regulatoria", set()))
    tecnicos = set(base.get("termos_tecnicos_fortes", set()))
    setoriais = set(base.get("termos_setoriais_regulatorios", set()))
    produtos_genericos = set(base.get("termos_produto_generico", set()))
    produtos_especificos = set(base.get("termos_produto_especifico", set()))
    termos_matches = set(base.get("termos_matches", set()))
    atos_normativos = set(base.get("termos_ato_normativo", set()))
    texto_norm = str(base.get("texto_contexto_normalizado") or "")

    tem_termo_sanitario_rebaixado = any(
        termo in texto_norm
        for termo in TERMOS_SANITARIOS_REBAIXAR_SEM_EMPRESA
    )
    tem_contexto_sanitario_generico = any(
        termo in texto_norm
        for termo in TERMOS_SANITARIOS_GENERICOS_SEM_PRODUTO
    )

    termos_produto_ou_setor = (
        setoriais
        | tecnicos.intersection(TERMOS_SETORIAIS_REGULATORIOS)
        | produtos_genericos.intersection(TERMOS_PRODUTOS_COMERCIALIZAVEIS_MONITORAMENTO)
        | produtos_especificos
        | termos_matches.intersection(TERMOS_SETORIAIS_REGULATORIOS)
    )

    if orgaos.intersection(TERMOS_ORGAOS_REBAIXAR_SEM_EMPRESA):
        return False, "órgão setorial rebaixado sem empresa direta", 0

    # IBAMA/MAPA só fica no monitoramento quando houver produto/assunto regulado
    # real, como RAPP, tóxico, químico, agrotóxico, rotulagem, FISPQ etc.
    if orgaos.intersection(TERMOS_ORGAOS_MONITORAMENTO_AMBIENTAL_PRODUTO):
        if (
            eventos.intersection(TERMOS_EVENTOS_MONITORAMENTO_FORTE)
            and termos_produto_ou_setor
            and (
                atividades.intersection(TERMOS_ATIVIDADES_PRODUTO_REGULADO)
                or tecnicos
                or setoriais
            )
        ):
            return (
                True,
                "órgão ambiental/agro + produto/tema regulado + evento material",
                6,
            )
        return False, "órgão ambiental/agro genérico sem produto regulado", 0

    # INMETRO é útil quando combina fiscalização/importação/interdição/apreensão
    # com produto comercializável, mesmo que genérico.
    if orgaos.intersection(TERMOS_ORGAOS_MONITORAMENTO_METROLOGIA):
        if (
            eventos.intersection({"apreensao", "interdicao", "produto apreendido", "produto interditado"})
            and (
                atividades.intersection({"importacao", "fiscalizacao"})
                or "importacao" in termos_matches
            )
            and termos_produto_ou_setor
        ):
            return (
                True,
                "INMETRO + produto comercializável + apreensão/interdição/importação",
                6,
            )
        return False, "INMETRO genérico sem produto comercializável relevante", 0

    # Receita Federal só fica no monitoramento quando houver comércio exterior
    # e evento material. Receita + processo/certificação isolados geram ruído.
    if orgaos.intersection(TERMOS_ORGAOS_MONITORAMENTO_COMEX):
        if (
            eventos.intersection({"auto de infracao", "autuacao", "apreensao", "multa", "irregularidade"})
            and atividades.intersection(TERMOS_ATIVIDADES_COMEX)
        ):
            return (
                True,
                "Receita Federal + importação/exportação + evento material",
                6,
            )
        return False, "Receita Federal sem importação/exportação material", 0

    # ANVISA/Vigilância sanitária só fica no monitoramento quando houver
    # tema sanitário aderente a produtos de varejo/regulação de produto.
    # Casos de biológicos, radiofármacos, sangue, tecidos, terapias avançadas
    # ou AFE/cancelamento genérico sem produto são rebaixados.
    if orgaos.intersection(TERMOS_ORGAOS_MONITORAMENTO_SANITARIO):
        if tem_termo_sanitario_rebaixado:
            return False, "ANVISA/Vigilância sanitária hospitalar/farmacêutica sem aderência Leroy", 0

        eventos_sanitarios = eventos.intersection({
            "cancelamento",
            "proibicao",
            "recolhimento",
            "interdicao",
            "suspensao",
            "irregularidade",
            "risco sanitario",
            "infracao sanitaria",
        })

        contexto_produto_sanitario = bool(
            termos_produto_ou_setor
            or atividades.intersection(TERMOS_ATIVIDADES_PRODUTO_REGULADO)
            or atos_normativos.intersection({"rdc", "regulamento", "regulamento tecnico", "resolucao"})
        )

        if eventos_sanitarios and contexto_produto_sanitario and not (
            tem_contexto_sanitario_generico and not termos_produto_ou_setor
        ):
            return (
                True,
                "ANVISA/Vigilância Sanitária + produto/tema sanitário aderente + evento material",
                6,
            )

        return False, "ANVISA/Vigilância sanitária genérica sem produto aderente", 0

    return False, "sem critério setorial útil para monitoramento", 0


def calcular_score_contextual_legado(matches: list[dict]) -> dict:
    categorias = {
        str(match.get("categoria") or "")
        for match in matches
    }

    categorias.discard("")

    tem_empresa = "empresa" in categorias
    tem_regulatorio = "regulatorio" in categorias
    tem_tecnico = "tecnico" in categorias
    tem_produto = "produto_ou_termo" in categorias
    tem_processo = "processo" in categorias

    if tem_empresa and (tem_regulatorio or tem_tecnico):
        return {
            "score_contextual": "FORTE",
            "nivel_contextual": 10,
            "motivo_contextual": "empresa + regulatório/técnico",
            "categorias_encontradas": sorted(categorias),
            "relevante_contextual": True,
        }

    if tem_produto and (tem_regulatorio or tem_tecnico):
        return {
            "score_contextual": "MEDIO",
            "nivel_contextual": 7,
            "motivo_contextual": "produto/termo + regulatório/técnico",
            "categorias_encontradas": sorted(categorias),
            "relevante_contextual": True,
        }

    if tem_empresa and tem_produto:
        return {
            "score_contextual": "MEDIO_ALTO",
            "nivel_contextual": 6,
            "motivo_contextual": "empresa + produto/termo",
            "categorias_encontradas": sorted(categorias),
            "relevante_contextual": True,
        }

    if tem_processo and (tem_tecnico or tem_regulatorio or tem_empresa):
        return {
            "score_contextual": "MEDIO",
            "nivel_contextual": 5,
            "motivo_contextual": "processo/protocolo + contexto técnico/regulatório/empresa",
            "categorias_encontradas": sorted(categorias),
            "relevante_contextual": True,
        }

    if matches:
        return {
            "score_contextual": "BAIXO",
            "nivel_contextual": 1,
            "motivo_contextual": "termo isolado sem combinação contextual",
            "categorias_encontradas": sorted(categorias),
            "relevante_contextual": False,
        }

    return {
        "score_contextual": "SEM_MATCH",
        "nivel_contextual": 0,
        "motivo_contextual": "sem matches",
        "categorias_encontradas": [],
        "relevante_contextual": False,
    }


def calcular_score_contextual_informativos_v3(
    matches: list[dict],
    texto_contexto: str = "",
) -> dict:
    base = montar_base_contextual(
        matches=matches,
        texto_contexto=texto_contexto,
    )

    tem_matches = bool(matches)
    tem_empresa = bool(base["termos_empresa"])
    tem_orgao_regulador = bool(base["termos_orgao_regulador"])
    tem_contexto_regulatorio_forte = bool(base["termos_contexto_regulatorio_forte"])
    tem_ato_normativo = bool(base["termos_ato_normativo"])
    tem_evento_material = bool(base["termos_evento_material"])
    tem_atividade_regulatoria = bool(base.get("termos_atividade_regulatoria"))
    tem_produto_especifico = bool(base["termos_produto_especifico"])

    tem_processo = bool(
        base["termos_matches"].intersection(TERMOS_PROCESSO)
        or "processo" in base["categorias"]
    )

    tem_contexto_administrativo_rebaixavel = (
        deve_rebaixar_contexto_administrativo_v9(base)
    )

    # ========================================================
    # V9 — TRAVA ADMINISTRATIVA/JUDICIAL/MILITAR SEM VÍNCULO
    # ========================================================
    # Produto comum em edital administrativo, militar, judicial, concurso,
    # universidade ou seleção não sustenta match se não houver Leroy,
    # órgão regulador real ou tema regulatório setorial.

    if tem_contexto_administrativo_rebaixavel:
        return montar_retorno_contextual(
            score="SEM_MATCH",
            nivel=0,
            motivo="contexto administrativo/judicial/militar sem empresa, órgão regulador real ou tema setorial",
            base=base,
            relevante=False,
        )

    # ========================================================
    # V9 — ÂNCORA EMPRESA
    # ========================================================
    # Empresa continua sendo a âncora principal. Quando Leroy/razão social
    # aparece, a publicação entra como match executivo mesmo que o restante
    # do contexto seja órgão, ato normativo, processo ou atividade regulatória.

    if tem_empresa and tem_evento_material:
        return montar_retorno_contextual(
            score="CRITICO",
            nivel=12,
            motivo="empresa + evento material",
            base=base,
            relevante=True,
        )

    if tem_empresa and tem_orgao_regulador:
        return montar_retorno_contextual(
            score="FORTE",
            nivel=11,
            motivo="empresa + órgão regulador",
            base=base,
            relevante=True,
        )

    if tem_empresa and tem_ato_normativo:
        return montar_retorno_contextual(
            score="FORTE",
            nivel=10,
            motivo="empresa + ato normativo/lei",
            base=base,
            relevante=True,
        )

    if tem_empresa and tem_produto_especifico:
        return montar_retorno_contextual(
            score="FORTE",
            nivel=9,
            motivo="empresa + produto específico",
            base=base,
            relevante=True,
        )

    if tem_empresa and tem_atividade_regulatoria:
        return montar_retorno_contextual(
            score="MEDIO_ALTO",
            nivel=8,
            motivo="empresa + atividade regulatória/comercial",
            base=base,
            relevante=True,
        )

    if tem_empresa and tem_processo:
        return montar_retorno_contextual(
            score="MEDIO_ALTO",
            nivel=7,
            motivo="empresa + processo/protocolo/requerimento",
            base=base,
            relevante=True,
        )

    if tem_empresa:
        return montar_retorno_contextual(
            score="MEDIO",
            nivel=6,
            motivo="empresa localizada sem outro contexto forte",
            base=base,
            relevante=True,
        )

    # ========================================================
    # V9 — SEM EMPRESA: MATRIZ EXECUTIVA MAIS RESTRITA
    # ========================================================
    # Sem empresa, o sistema não deve promover produto comum em contexto
    # administrativo. Match executivo sem empresa exige órgão regulador real.

    if (
        tem_produto_especifico
        and tem_evento_material
        and tem_orgao_regulador
    ):
        return montar_retorno_contextual(
            score="FORTE",
            nivel=8,
            motivo="produto específico + órgão regulador real + evento material",
            base=base,
            relevante=True,
        )

    if (
        tem_produto_especifico
        and tem_orgao_regulador
        and tem_atividade_regulatoria
    ):
        return montar_retorno_contextual(
            score="MEDIO_ALTO",
            nivel=7,
            motivo="produto específico + órgão regulador real + atividade regulatória",
            base=base,
            relevante=True,
        )

    if (
        tem_produto_especifico
        and tem_orgao_regulador
        and tem_ato_normativo
    ):
        return montar_retorno_contextual(
            score="MEDIO",
            nivel=6,
            motivo="produto específico + órgão regulador real + ato normativo/lei",
            base=base,
            relevante=True,
        )

    # ========================================================
    # V8 — SEM EMPRESA: MONITORAMENTO SETORIAL CALIBRADO
    # ========================================================
    # A triagem manual mostrou que o monitoramento deve ficar restrito a
    # cenários setoriais úteis. Casos genéricos de CREA/CAT, ANP gás/GLP,
    # IBAMA/MAPA sem produto regulado e Receita sem importação/exportação
    # são rebaixados para SEM_MATCH contextual.

    manter_monitoramento, motivo_monitoramento, nivel_monitoramento = (
        avaliar_monitoramento_setorial_v8(base)
    )

    if manter_monitoramento:
        return montar_retorno_contextual(
            score="MONITORAMENTO_SETORIAL",
            nivel=nivel_monitoramento,
            motivo=motivo_monitoramento,
            base=base,
            relevante=False,
        )

    if tem_produto_especifico and tem_evento_material:
        return montar_retorno_contextual(
            score="REVISAO",
            nivel=4,
            motivo="produto específico + evento material sem órgão/empresa",
            base=base,
            relevante=False,
        )

    # Órgão/regra forte + evento material, sem empresa e sem produto específico,
    # não vira mais revisão automaticamente. Após a V8, isso foi considerado
    # ruído contextual quando não atende aos critérios de monitoramento setorial.

    if tem_produto_especifico and tem_contexto_regulatorio_forte:
        return montar_retorno_contextual(
            score="REVISAO",
            nivel=3,
            motivo="produto específico + órgão/regra forte sem evento/atividade",
            base=base,
            relevante=False,
        )

    if tem_matches:
        return montar_retorno_contextual(
            score="BAIXO",
            nivel=1,
            motivo="termos detectados sem combinação contextual executiva",
            base=base,
            relevante=False,
        )

    return montar_retorno_contextual(
        score="SEM_MATCH",
        nivel=0,
        motivo="sem matches",
        base=base,
        relevante=False,
    )

def calcular_score_contextual(
    matches: list[dict],
    texto_contexto: str = "",
    modelo_planilha: str = DEFAULT_MODELO_PLANILHA,
) -> dict:
    if modelo_planilha == "simples_coluna_unica_v1":
        return calcular_score_contextual_informativos_v3(
            matches=matches,
            texto_contexto=texto_contexto,
        )

    return calcular_score_contextual_legado(matches)


def deve_filtrar_por_contexto(modelo_planilha: str) -> bool:
    return modelo_planilha == "simples_coluna_unica_v1"



# ============================================================
# LOGS DE PROGRESSO — MATCH
# ============================================================

LOG_MATCH_DETALHADO = True
LOG_MATCH_HIBRIDO_A_CADA = 50
LOG_MATCH_PUBLICACAO_LENTA_SEG = 10
LOG_MATCH_PUBLICACAO_MUITO_LENTA_SEG = 30


def _agora_log() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _titulo_log_publicacao(registro: dict, limite: int = 120) -> str:
    titulo = (
        registro.get("titulo")
        or registro.get("titulo_publicacao")
        or registro.get("title")
        or registro.get("ementa")
        or ""
    )

    titulo = re.sub(r"\s+", " ", str(titulo)).strip()

    if not titulo:
        return "(sem título)"

    if len(titulo) > limite:
        return titulo[: limite - 3].rstrip() + "..."

    return titulo


def _log_match(mensagem: str) -> None:
    if LOG_MATCH_DETALHADO:
        print(f"[{_agora_log()}] {mensagem}", flush=True)


# ============================================================
# EXECUÇÃO DO MATCH
# ============================================================

def aplicar_match_publicacao(
    registro: dict,
    palavras_texto: list[dict],
    palavras_numero: list[dict],
    palavras_hibrido: list[dict],
    processos: list[str],
    termos_exclusao: list[str],
    termos_resgate: list[str],
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG,
    modelo_planilha: str = DEFAULT_MODELO_PLANILHA,
    contexto_log: dict | None = None,
) -> dict:

    bloqueado, termo_bloqueio = publicacao_bloqueada_por_exclusao(
        registro=registro,
        termos_exclusao=termos_exclusao
    )

    resgatado = False
    termo_resgate = None

    if bloqueado:
        resgatado, termo_resgate = publicacao_resgatada_por_relevancia(
            registro=registro,
            termos_resgate=termos_resgate,
            modo_conservador=deve_filtrar_por_contexto(modelo_planilha),
        )

        if not resgatado:
            registro_saida = dict(registro)
            registro_saida["matchs_detectados"] = []
            registro_saida["matchs"] = []
            registro_saida["status_match"] = "SEM_MATCH"
            registro_saida["status_exclusao"] = "EXCLUIDO_POR_TITULO"
            registro_saida["status_resgate"] = "NAO_RESGATADO"
            registro_saida["termo_exclusao_aplicado"] = termo_bloqueio
            registro_saida["termo_resgate_aplicado"] = None
            registro_saida["quantidade_matchs_detectados"] = 0
            registro_saida["quantidade_matchs"] = 0
            registro_saida["finalidade_config"] = finalidade_config
            registro_saida["modelo_planilha"] = modelo_planilha
            registro_saida["score_contextual"] = "EXCLUIDO"
            registro_saida["nivel_contextual"] = 0
            registro_saida["motivo_contextual"] = (
                f"publicação excluída por título: {termo_bloqueio}"
            )
            registro_saida["categorias_encontradas"] = []
            registro_saida["relevante_contextual"] = False
            return registro_saida

    texto_match = montar_texto_match_publicacao(
        registro=registro,
        modelo_planilha=modelo_planilha,
    )

    matches_raw = []

    matches_raw.extend(
        contem_palavra(
            texto=texto_match,
            palavras_textuais=palavras_texto,
            termos_exclusao=termos_exclusao
        )
    )

    matches_raw.extend(
        contem_processo(
            texto=texto_match,
            processos=processos
        )
    )

    matches_raw.extend(
        contem_numeros_substring(
            texto=texto_match,
            termos=palavras_numero,
            contexto_log={
                **(contexto_log or {}),
                "tipo": "NUMERO",
            } if palavras_numero else None,
        )
    )

    matches_raw.extend(
        contem_numeros_substring(
            texto=texto_match,
            termos=palavras_hibrido,
            contexto_log={
                **(contexto_log or {}),
                "tipo": "HIBRIDO",
            } if palavras_hibrido else None,
        )
    )

    matches_detectados = consolidar_matches(matches_raw)
    contexto = calcular_score_contextual(
        matches=matches_detectados,
        texto_contexto=montar_texto_resgate(registro),
        modelo_planilha=modelo_planilha,
    )

    score_contextual = contexto.get("score_contextual")
    em_revisao_contextual = score_contextual in {"REVISAO", "MONITORAMENTO_SETORIAL"}

    if deve_filtrar_por_contexto(modelo_planilha):
        matches_validos = (
            matches_detectados
            if contexto.get("relevante_contextual")
            else []
        )
        matches_revisao = matches_detectados if em_revisao_contextual else []
    else:
        matches_validos = matches_detectados
        matches_revisao = []

    registro_saida = dict(registro)
    registro_saida["matchs_detectados"] = matches_detectados
    registro_saida["matchs"] = matches_validos
    registro_saida["matchs_revisao"] = matches_revisao
    registro_saida["status_match"] = (
        "COM_MATCH" if matches_validos else "SEM_MATCH"
    )
    if resgatado and matches_validos:
        status_exclusao = "RESGATADO_DE_EXCLUSAO"
        status_resgate = "RESGATADO"
    elif resgatado and not matches_validos:
        status_exclusao = "EXCLUIDO_POR_TITULO"
        status_resgate = "RESGATE_SEM_MATCH_VALIDO"
    else:
        status_exclusao = "NAO_EXCLUIDO"
        status_resgate = "NAO_APLICAVEL"

    registro_saida["status_exclusao"] = status_exclusao
    registro_saida["status_resgate"] = status_resgate
    registro_saida["termo_exclusao_aplicado"] = (
        termo_bloqueio if resgatado else None
    )
    registro_saida["termo_resgate_aplicado"] = termo_resgate
    registro_saida["quantidade_matchs_detectados"] = len(matches_detectados)
    registro_saida["quantidade_matchs"] = len(matches_validos)
    registro_saida["quantidade_matchs_revisao"] = len(matches_revisao)
    registro_saida["processos_monitorados_detectados"] = [
        match.get("termo")
        for match in matches_detectados
        if match.get("categoria") == "processo"
    ]
    registro_saida["status_revisao_contextual"] = (
        "MONITORAMENTO_SETORIAL" if score_contextual == "MONITORAMENTO_SETORIAL" else ("EM_REVISAO" if matches_revisao else "NAO_APLICAVEL")
    )
    registro_saida["finalidade_config"] = finalidade_config
    registro_saida["modelo_planilha"] = modelo_planilha
    registro_saida.update(contexto)

    if resgatado and matches_validos:
        registro_saida["motivo_resgate"] = (
            f"publicação tinha exclusão '{termo_bloqueio}', "
            f"mas foi resgatada por '{termo_resgate}'"
        )
    elif resgatado and not matches_validos:
        registro_saida["motivo_resgate"] = (
            f"publicação tinha exclusão '{termo_bloqueio}' e até encontrou "
            f"termo de resgate '{termo_resgate}', mas não passou no contexto"
        )

    return registro_saida


def aplicar_match_base(
    registros: list[dict],
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG
) -> list[dict]:
    palavras, processos, caminhos = carregar_palavras_chave(
        finalidade_config=finalidade_config
    )

    termos_exclusao = carregar_exclusoes(
        finalidade_config=finalidade_config
    )

    termos_resgate = carregar_resgates(
        finalidade_config=finalidade_config
    )

    modelo_planilha = caminhos.get("modelo_planilha")

    palavras_texto = [
        p for p in palavras
        if p.get("tipo") == "texto"
    ]

    palavras_numero = [
        p for p in palavras
        if p.get("tipo") == "numero"
    ]

    palavras_hibrido = [
        p for p in palavras
        if p.get("tipo") == "hibrido"
    ]

    resultados = []
    total = len(registros)

    print("=" * 80)
    print("MATCH — CONFIGURAÇÃO")
    print(f"Finalidade config: {finalidade_config}")
    print(f"Modelo planilha: {modelo_planilha}")
    print(f"Pasta config: {caminhos.get('pasta_config')}")
    print(f"Arquivo palavras: {caminhos.get('palavras_excel')}")
    print(f"Arquivo exclusões: {caminhos.get('exclusoes_excel')}")
    print(f"Arquivo resgates: {caminhos.get('resgates_excel')}")
    print(f"Palavras texto: {len(palavras_texto)}")
    print(f"Palavras número: {len(palavras_numero)}")
    print(f"Palavras híbridas: {len(palavras_hibrido)}")
    print(f"Processos: {len(processos)}")
    print(f"Exclusões: {len(termos_exclusao)}")
    print(f"Resgates: {len(termos_resgate)}")
    print(f"Filtro contextual: {deve_filtrar_por_contexto(modelo_planilha)}")
    print("=" * 80)

    inicio_geral = time.perf_counter()
    _log_match(
        f"[MATCH] INÍCIO | finalidade={finalidade_config} | "
        f"total_publicacoes={total} | texto={len(palavras_texto)} | "
        f"numero={len(palavras_numero)} | hibrido={len(palavras_hibrido)} | "
        f"processos={len(processos)}"
    )

    for idx, registro in enumerate(registros, start=1):
        inicio_publicacao = time.perf_counter()
        titulo_log = _titulo_log_publicacao(registro)

        _log_match(
            f"[MATCH] {idx}/{total} | INICIANDO | "
            f"titulo={titulo_log}"
        )

        resultado = aplicar_match_publicacao(
            registro=registro,
            palavras_texto=palavras_texto,
            palavras_numero=palavras_numero,
            palavras_hibrido=palavras_hibrido,
            processos=processos,
            termos_exclusao=termos_exclusao,
            termos_resgate=termos_resgate,
            finalidade_config=finalidade_config,
            modelo_planilha=modelo_planilha,
            contexto_log={
                "pub_atual": idx,
                "pub_total": total,
                "titulo": titulo_log,
                "finalidade_config": finalidade_config,
            },
        )

        resultados.append(resultado)

        tempo_publicacao = time.perf_counter() - inicio_publicacao

        if tempo_publicacao >= LOG_MATCH_PUBLICACAO_MUITO_LENTA_SEG:
            nivel_lentidao = "MUITO_LENTO"
        elif tempo_publicacao >= LOG_MATCH_PUBLICACAO_LENTA_SEG:
            nivel_lentidao = "LENTO"
        else:
            nivel_lentidao = "OK"

        _log_match(
            f"[MATCH] {idx}/{total} | CONCLUIDO | "
            f"status={resultado.get('status_match')} | "
            f"detectados={resultado.get('quantidade_matchs_detectados', 0)} | "
            f"validos={resultado.get('quantidade_matchs', 0)} | "
            f"tempo={tempo_publicacao:.1f}s | "
            f"nivel={nivel_lentidao}"
        )

        if idx % 10 == 0 or idx == total:
            tempo_total = time.perf_counter() - inicio_geral
            media = tempo_total / idx if idx else 0
            restante = max(total - idx, 0) * media

            print(
                f"[MATCH] PROGRESSO {idx}/{total} | "
                f"tempo_total={tempo_total:.1f}s | "
                f"media={media:.1f}s/pub | "
                f"estimativa_restante={restante:.1f}s",
                flush=True,
            )

    return resultados


def salvar_resultado_match(
    data_referencia: str,
    registros: list[dict],
    finalidade_config: str = DEFAULT_FINALIDADE_CONFIG
) -> Path:
    caminhos = obter_caminhos_config(finalidade_config)
    match_dir = MATCH_BASE_DIR / finalidade_config
    match_dir.mkdir(parents=True, exist_ok=True)

    caminho = match_dir / f"match_publicacoes_{data_referencia}.json"

    total_com_match = sum(
        1 for r in registros
        if r.get("status_match") == "COM_MATCH"
    )

    total_sem_match = sum(
        1 for r in registros
        if r.get("status_match") == "SEM_MATCH"
    )

    total_com_termo_detectado = sum(
        1 for r in registros
        if r.get("quantidade_matchs_detectados", 0) > 0
    )

    total_excluidos_titulo = sum(
        1 for r in registros
        if r.get("status_exclusao") == "EXCLUIDO_POR_TITULO"
    )

    total_resgatados = sum(
        1 for r in registros
        if r.get("status_resgate") == "RESGATADO"
    )

    total_revisao_contextual = sum(
        1 for r in registros
        if r.get("status_revisao_contextual") == "EM_REVISAO"
    )

    total_monitoramento_setorial = sum(
        1 for r in registros
        if r.get("status_revisao_contextual") == "MONITORAMENTO_SETORIAL"
    )

    total_monitoramento_contextual = (
        total_com_match
        + total_revisao_contextual
        + total_monitoramento_setorial
    )

    payload = {
        "data_referencia": data_referencia,
        "finalidade_config": finalidade_config,
        "modelo_planilha": caminhos.get("modelo_planilha"),
        "pasta_config": str(caminhos.get("pasta_config")),
        "arquivo_palavras_chave": str(caminhos.get("palavras_excel")),
        "arquivo_exclusoes": str(caminhos.get("exclusoes_excel")),
        "arquivo_resgates": str(caminhos.get("resgates_excel")),
        "total_registros": len(registros),
        "total_com_match": total_com_match,
        "total_sem_match": total_sem_match,
        "total_com_termo_detectado": total_com_termo_detectado,
        "total_excluidos_titulo": total_excluidos_titulo,
        "total_resgatados": total_resgatados,
        "total_revisao_contextual": total_revisao_contextual,
        "total_monitoramento_setorial": total_monitoramento_setorial,
        "total_monitoramento_contextual": total_monitoramento_contextual,
        "registros": registros,
    }

    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return caminho
