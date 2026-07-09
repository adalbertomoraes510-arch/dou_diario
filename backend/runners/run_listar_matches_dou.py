# ============================================================
# RUNNER — Listar Matches DOU
# Mostra no terminal as publicações relevantes e suspeitas
# Lê prioritariamente a auditoria nova
# ============================================================

import json
import datetime
import sys
from pathlib import Path


# ============================================================
# CONFIGURAÇÃO
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 12)
FINALIDADE = "dou_diario"

# Limite da amostra de texto exibida no terminal
LIMITE_AMOSTRA_TERMINAL = 300

ROOT_DIR = Path(__file__).resolve().parents[2]

ARQUIVO_MATCH = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "match"
    / FINALIDADE
    / f"match_publicacoes_{DATA_EXECUCAO.isoformat()}.json"
)

ARQUIVO_AUDITORIA = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "auditoria"
    / FINALIDADE
    / f"auditoria_match_{DATA_EXECUCAO.isoformat()}.json"
)


# ============================================================
# AJUSTE UTF-8 TERMINAL
# ============================================================

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def carregar_json(caminho: Path):
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    return json.loads(caminho.read_text(encoding="utf-8"))


def extrair_registros(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        if isinstance(payload.get("registros"), list):
            return payload["registros"]

        if isinstance(payload.get("publicacoes"), list):
            return payload["publicacoes"]

    return []


def buscar_valor(registro: dict, chaves: list[str], padrao=""):
    for chave in chaves:
        valor = registro.get(chave)

        if valor not in [None, ""]:
            return valor

    return padrao


def imprimir_linha():
    print("-" * 80)


def imprimir_titulo(texto: str):
    print("=" * 80)
    print(texto)
    print("=" * 80)


def formatar_lista(valor):
    if valor is None:
        return []

    if isinstance(valor, list):
        return valor

    return [valor]


def limitar_texto(texto: str, limite: int = LIMITE_AMOSTRA_TERMINAL) -> str:
    texto = str(texto or "").replace("\n", " ").replace("\r", " ")
    texto = " ".join(texto.split())

    if len(texto) <= limite:
        return texto

    return texto[:limite].rstrip() + "..."


def obter_termos_publicacao(publicacao: dict) -> list:
    termos = buscar_valor(
        publicacao,
        [
            "termos_encontrados",
            "palavras_encontradas",
            "palavras_chave_encontradas",
            "palavras_chave",
        ],
        padrao=[]
    )

    return formatar_lista(termos)


def obter_detalhes_publicacao(publicacao: dict) -> list:
    detalhes = buscar_valor(
        publicacao,
        [
            "termos",
            "matchs",
            "matches",
            "detalhes_match",
            "resultado_match",
        ],
        padrao=[]
    )

    return formatar_lista(detalhes)


def imprimir_json_resumido(valor):
    print(json.dumps(valor, ensure_ascii=False, indent=2))


def imprimir_publicacao(publicacao: dict, indice: int, prefixo: str):
    titulo = buscar_valor(
        publicacao,
        ["titulo", "titulo_publicacao"],
        padrao="SEM_TITULO"
    )

    orgao = buscar_valor(
        publicacao,
        ["orgao", "orgao_publicacao"],
        padrao="NAO_IDENTIFICADO"
    )

    secao = buscar_valor(publicacao, ["secao"], padrao="")
    pagina = buscar_valor(publicacao, ["pagina"], padrao="")
    url = buscar_valor(publicacao, ["url", "link"], padrao="")

    score = buscar_valor(
        publicacao,
        ["score_publicacao", "score", "nivel_score", "classificacao_score"],
        padrao=""
    )

    quantidade_matchs = buscar_valor(
        publicacao,
        ["quantidade_matchs"],
        padrao=""
    )

    termos = obter_termos_publicacao(publicacao)
    detalhes = obter_detalhes_publicacao(publicacao)

    print(f"{prefixo} {indice}")
    imprimir_linha()
    print(f"Título: {titulo}")
    print(f"Órgão: {orgao}")
    print(f"Seção: {secao}")
    print(f"Página: {pagina}")
    print(f"Score: {score}")
    print(f"Quantidade de matchs: {quantidade_matchs}")
    print(f"URL: {url}")

    print("Termos encontrados:")
    imprimir_json_resumido(termos)

    print("Detalhes:")
    imprimir_json_resumido(detalhes)

    imprimir_linha()


def imprimir_falso_positivo_tecnico(item: dict, indice: int):
    titulo = item.get("titulo") or "SEM_TITULO"
    orgao = item.get("orgao") or "NAO_IDENTIFICADO"
    secao = item.get("secao") or ""
    pagina = item.get("pagina") or ""
    url = item.get("url") or ""
    termo = item.get("termo") or ""
    tipo = item.get("tipo") or ""
    encontrados = item.get("encontrados", [])
    score = item.get("score_confianca") or ""
    motivos = item.get("motivos", [])
    amostra_texto = limitar_texto(
        item.get("amostra_texto", ""),
        limite=LIMITE_AMOSTRA_TERMINAL
    )

    print(f"POSSÍVEL FALSO POSITIVO {indice}")
    imprimir_linha()
    print(f"Título: {titulo}")
    print(f"Órgão: {orgao}")
    print(f"Seção: {secao}")
    print(f"Página: {pagina}")
    print(f"Termo: {termo}")
    print(f"Tipo: {tipo}")
    print(f"Score confiança: {score}")
    print(f"URL: {url}")

    print("Encontrados:")
    imprimir_json_resumido(encontrados)

    print("Motivos:")
    imprimir_json_resumido(motivos)

    print(f"Amostra resumida ({LIMITE_AMOSTRA_TERMINAL} caracteres):")
    print(amostra_texto)

    imprimir_linha()


# ============================================================
# MODO PRINCIPAL — AUDITORIA NOVA
# ============================================================

def listar_por_auditoria():
    payload_auditoria = carregar_json(ARQUIVO_AUDITORIA)

    resumo = payload_auditoria.get("resumo_executivo", {})
    consolidado = payload_auditoria.get(
        "resumo_executivo_consolidado",
        {}
    )

    visao_geral = consolidado.get("visao_geral", {})

    publicacoes_com_match = payload_auditoria.get(
        "publicacoes_com_match",
        []
    )

    publicacoes_confirmadas = payload_auditoria.get(
        "publicacoes_relevantes_confirmadas",
        []
    )

    publicacoes_suspeitas = payload_auditoria.get(
        "publicacoes_com_suspeita_falso_positivo",
        []
    )

    possiveis_falsos_positivos = payload_auditoria.get(
        "possiveis_falsos_positivos",
        []
    )

    imprimir_titulo("LISTAGEM EXECUTIVA DE MATCHES DOU")
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Finalidade: {FINALIDADE}")
    print(f"Arquivo auditoria: {ARQUIVO_AUDITORIA}")
    print(f"Arquivo match bruto: {ARQUIVO_MATCH}")

    imprimir_titulo("RESUMO EXECUTIVO")
    print(f"Total publicações: {resumo.get('total_publicacoes', 0)}")
    print(f"Com match: {resumo.get('com_match', 0)}")
    print(f"Sem match: {resumo.get('sem_match', 0)}")
    print(f"Total matchs: {resumo.get('total_matchs', 0)}")
    print(f"Taxa match: {resumo.get('taxa_match', 0)}%")
    print(
        "Publicações relevantes confirmadas: "
        f"{len(publicacoes_confirmadas)}"
    )
    print(
        "Publicações com suspeita de falso positivo: "
        f"{len(publicacoes_suspeitas)}"
    )
    print(
        "Possíveis falsos positivos: "
        f"{len(possiveis_falsos_positivos)}"
    )
    print(
        "Taxa match confirmado: "
        f"{visao_geral.get('taxa_match_confirmado', resumo.get('taxa_match_confirmado', 0))}%"
    )

    imprimir_titulo("PUBLICAÇÕES RELEVANTES CONFIRMADAS")
    print(f"Total: {len(publicacoes_confirmadas)}")
    print("=" * 80)

    if not publicacoes_confirmadas:
        print("Nenhuma publicação relevante confirmada.")
    else:
        for i, publicacao in enumerate(publicacoes_confirmadas, start=1):
            imprimir_publicacao(
                publicacao=publicacao,
                indice=i,
                prefixo="RELEVANTE CONFIRMADA"
            )

    imprimir_titulo("SUSPEITAS / POSSÍVEIS FALSOS POSITIVOS")
    print(f"Total: {len(publicacoes_suspeitas)}")
    print("=" * 80)

    if not publicacoes_suspeitas:
        print("Nenhuma publicação suspeita encontrada.")
    else:
        for i, publicacao in enumerate(publicacoes_suspeitas, start=1):
            imprimir_publicacao(
                publicacao=publicacao,
                indice=i,
                prefixo="SUSPEITA"
            )

    imprimir_titulo("DETALHE TÉCNICO DOS POSSÍVEIS FALSOS POSITIVOS")
    print(f"Total: {len(possiveis_falsos_positivos)}")
    print("=" * 80)

    if not possiveis_falsos_positivos:
        print("Nenhum possível falso positivo técnico encontrado.")
    else:
        for i, item in enumerate(possiveis_falsos_positivos, start=1):
            imprimir_falso_positivo_tecnico(item=item, indice=i)

    imprimir_titulo("VALIDAÇÃO FINAL")
    print(f"Publicações com match: {len(publicacoes_com_match)}")
    print(f"Relevantes confirmadas: {len(publicacoes_confirmadas)}")
    print(f"Com suspeita falso positivo: {len(publicacoes_suspeitas)}")
    print(f"Possíveis falsos positivos: {len(possiveis_falsos_positivos)}")
    print("=" * 80)


# ============================================================
# FALLBACK — MATCH BRUTO ANTIGO
# ============================================================

def listar_por_match_bruto():
    payload_match = carregar_json(ARQUIVO_MATCH)
    registros = extrair_registros(payload_match)

    matches = [
        registro
        for registro in registros
        if registro.get("status_match") == "COM_MATCH"
    ]

    imprimir_titulo("LISTAGEM DE MATCHES DOU — MODO MATCH BRUTO")
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Finalidade: {FINALIDADE}")
    print(f"Arquivo match: {ARQUIVO_MATCH}")
    print("=" * 80)
    print(f"Total registros no arquivo: {len(registros)}")
    print(f"Total com match: {len(matches)}")
    print("=" * 80)

    if not matches:
        print("Nenhum match encontrado.")
        return

    for i, registro in enumerate(matches, start=1):
        imprimir_publicacao(
            publicacao=registro,
            indice=i,
            prefixo="MATCH"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    if ARQUIVO_AUDITORIA.exists():
        listar_por_auditoria()
        return

    print(
        "Arquivo de auditoria não encontrado. "
        "Usando fallback pelo match bruto."
    )

    listar_por_match_bruto()


if __name__ == "__main__":
    main()