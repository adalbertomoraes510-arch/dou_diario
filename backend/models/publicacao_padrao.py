# ============================================================
# MODELO PADRÃO DE PUBLICAÇÃO MULTI-FONTE
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Definir um contrato único de publicação para que diferentes
# fontes, como DOU, ANVISA, Inmetro, GovSP e outras, possam
# entregar dados em um formato comum.
#
# Este arquivo NÃO altera o fluxo atual do DOU.
# Ele apenas cria a base técnica para evolução multi-fonte.
# ============================================================

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
# CONSTANTES DO CONTRATO
# ============================================================

STATUS_NORMALIZACAO_OK = "OK"
STATUS_NORMALIZACAO_INCOMPLETA = "INCOMPLETA"
STATUS_NORMALIZACAO_INVALIDA = "INVALIDA"


CAMPOS_OBRIGATORIOS_PUBLICACAO_PADRAO = [
    "id_publicacao",
    "fonte",
    "data_publicacao",
    "titulo",
    "orgao",
    "url",
    "texto_integral",
]


CAMPOS_OPCIONAIS_PUBLICACAO_PADRAO = [
    "secao",
    "pagina",
    "tipo_publicacao",
    "numero_processo",
    "palavras_chave_detectadas",
    "metadados",
    "data_coleta",
    "hash_conteudo",
    "origem_arquivo",
    "status_normalizacao",
]


# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def normalizar_texto_basico(valor: Any) -> str:
    """
    Normaliza valores textuais básicos para evitar None, quebras
    excessivas de linha e espaços duplicados.
    """
    if valor is None:
        return ""

    texto = str(valor).strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def normalizar_fonte(fonte: Any) -> str:
    """
    Padroniza o identificador da fonte.

    Exemplos:
    - "DOU" -> "dou"
    - "Gov SP" -> "gov_sp"
    - "ANVISA" -> "anvisa"
    """
    texto = normalizar_texto_basico(fonte).lower()
    texto = texto.replace("-", "_")
    texto = texto.replace(" ", "_")
    texto = re.sub(r"[^a-z0-9_]", "", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto


def data_em_formato_iso(data: Any) -> str:
    """
    Converte uma data para formato ISO YYYY-MM-DD quando possível.

    Aceita:
    - datetime/date
    - string no formato YYYY-MM-DD
    - string no formato DD/MM/YYYY
    """
    if data is None:
        return ""

    if hasattr(data, "strftime"):
        return data.strftime("%Y-%m-%d")

    texto = normalizar_texto_basico(data)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return texto

    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", texto):
        try:
            return datetime.strptime(texto, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return texto

    return texto


def gerar_hash_conteudo(
    fonte: str,
    data_publicacao: str,
    titulo: str,
    orgao: str,
    url: str,
    texto_integral: str,
) -> str:
    """
    Gera hash técnico do conteúdo da publicação.

    Este hash ajuda a:
    - identificar alterações;
    - evitar duplicidades;
    - auditar reprocessamentos;
    - manter rastreabilidade entre fontes.
    """
    base = "|".join(
        [
            normalizar_fonte(fonte),
            data_em_formato_iso(data_publicacao),
            normalizar_texto_basico(titulo).lower(),
            normalizar_texto_basico(orgao).lower(),
            normalizar_texto_basico(url).lower(),
            normalizar_texto_basico(texto_integral).lower(),
        ]
    )

    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def gerar_id_publicacao(
    fonte: str,
    data_publicacao: str,
    titulo: str,
    orgao: str,
    url: str,
    texto_integral: str,
) -> str:
    """
    Gera um ID técnico padronizado para a publicação.

    Padrão:

    fonte_data_hash12

    Exemplo:

    dou_2026_05_14_a1b2c3d4e5f6
    """
    fonte_normalizada = normalizar_fonte(fonte) or "fonte_indefinida"
    data_iso = data_em_formato_iso(data_publicacao) or "data_indefinida"
    data_id = data_iso.replace("-", "_")

    hash_conteudo = gerar_hash_conteudo(
        fonte=fonte_normalizada,
        data_publicacao=data_iso,
        titulo=titulo,
        orgao=orgao,
        url=url,
        texto_integral=texto_integral,
    )

    return f"{fonte_normalizada}_{data_id}_{hash_conteudo[:12]}"


def validar_data_iso(data_publicacao: str) -> bool:
    """
    Valida se a data está no formato YYYY-MM-DD.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_publicacao or ""):
        return False

    try:
        datetime.strptime(data_publicacao, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ============================================================
# MODELO PRINCIPAL
# ============================================================

@dataclass
class PublicacaoPadrao:
    """
    Contrato padrão de publicação multi-fonte.

    Qualquer fonte futura deve entregar seus dados neste formato,
    permitindo reaproveitar:

    - match_service.py;
    - auditoria_match_service.py;
    - relatorio_executivo_dou_service.py ou serviço futuro genérico;
    - consolidados por período;
    - fechamento mensal;
    - front/API.
    """

    id_publicacao: str
    fonte: str
    data_publicacao: str
    titulo: str
    orgao: str
    url: str
    texto_integral: str

    secao: str = ""
    pagina: str = ""
    tipo_publicacao: str = ""
    numero_processo: str = ""
    palavras_chave_detectadas: List[str] = field(default_factory=list)
    metadados: Dict[str, Any] = field(default_factory=dict)

    data_coleta: str = ""
    hash_conteudo: str = ""
    origem_arquivo: str = ""
    status_normalizacao: str = STATUS_NORMALIZACAO_OK

    def validar(self) -> Dict[str, Any]:
        """
        Valida se a publicação atende ao contrato mínimo.

        Retorno:

        {
            "valido": bool,
            "erros": [...],
            "avisos": [...]
        }
        """
        erros: List[str] = []
        avisos: List[str] = []

        if not normalizar_texto_basico(self.id_publicacao):
            erros.append("Campo obrigatório ausente: id_publicacao")

        if not normalizar_texto_basico(self.fonte):
            erros.append("Campo obrigatório ausente: fonte")

        if not normalizar_texto_basico(self.data_publicacao):
            erros.append("Campo obrigatório ausente: data_publicacao")
        elif not validar_data_iso(self.data_publicacao):
            erros.append("Campo data_publicacao deve estar no formato YYYY-MM-DD")

        if not normalizar_texto_basico(self.titulo):
            erros.append("Campo obrigatório ausente: titulo")

        if not normalizar_texto_basico(self.orgao):
            erros.append("Campo obrigatório ausente: orgao")

        if not normalizar_texto_basico(self.url):
            avisos.append("Campo url está vazio. Aceitável apenas para fontes sem URL pública.")

        if not normalizar_texto_basico(self.texto_integral):
            erros.append("Campo obrigatório ausente: texto_integral")

        if not self.hash_conteudo:
            avisos.append("Campo hash_conteudo vazio. Recomenda-se gerar hash para auditoria.")

        return {
            "valido": len(erros) == 0,
            "erros": erros,
            "avisos": avisos,
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Converte o modelo para dicionário serializável em JSON.
        """
        return {
            "id_publicacao": self.id_publicacao,
            "fonte": self.fonte,
            "data_publicacao": self.data_publicacao,
            "titulo": self.titulo,
            "orgao": self.orgao,
            "url": self.url,
            "texto_integral": self.texto_integral,
            "secao": self.secao,
            "pagina": self.pagina,
            "tipo_publicacao": self.tipo_publicacao,
            "numero_processo": self.numero_processo,
            "palavras_chave_detectadas": self.palavras_chave_detectadas,
            "metadados": self.metadados,
            "data_coleta": self.data_coleta,
            "hash_conteudo": self.hash_conteudo,
            "origem_arquivo": self.origem_arquivo,
            "status_normalizacao": self.status_normalizacao,
        }

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "PublicacaoPadrao":
        """
        Cria uma PublicacaoPadrao a partir de um dicionário.
        """
        return cls(
            id_publicacao=normalizar_texto_basico(dados.get("id_publicacao")),
            fonte=normalizar_fonte(dados.get("fonte")),
            data_publicacao=data_em_formato_iso(dados.get("data_publicacao")),
            titulo=normalizar_texto_basico(dados.get("titulo")),
            orgao=normalizar_texto_basico(dados.get("orgao")),
            url=normalizar_texto_basico(dados.get("url")),
            texto_integral=normalizar_texto_basico(dados.get("texto_integral")),
            secao=normalizar_texto_basico(dados.get("secao")),
            pagina=normalizar_texto_basico(dados.get("pagina")),
            tipo_publicacao=normalizar_texto_basico(dados.get("tipo_publicacao")),
            numero_processo=normalizar_texto_basico(dados.get("numero_processo")),
            palavras_chave_detectadas=dados.get("palavras_chave_detectadas") or [],
            metadados=dados.get("metadados") or {},
            data_coleta=normalizar_texto_basico(dados.get("data_coleta")),
            hash_conteudo=normalizar_texto_basico(dados.get("hash_conteudo")),
            origem_arquivo=normalizar_texto_basico(dados.get("origem_arquivo")),
            status_normalizacao=normalizar_texto_basico(
                dados.get("status_normalizacao")
            ) or STATUS_NORMALIZACAO_OK,
        )


# ============================================================
# CONSTRUÇÃO PADRONIZADA
# ============================================================

def construir_publicacao_padrao(
    fonte: str,
    data_publicacao: Any,
    titulo: Any,
    orgao: Any,
    url: Any,
    texto_integral: Any,
    secao: Any = "",
    pagina: Any = "",
    tipo_publicacao: Any = "",
    numero_processo: Any = "",
    palavras_chave_detectadas: Optional[List[str]] = None,
    metadados: Optional[Dict[str, Any]] = None,
    origem_arquivo: Any = "",
) -> PublicacaoPadrao:
    """
    Cria uma publicação padrão já com fonte, data, hash e ID normalizados.
    """
    fonte_normalizada = normalizar_fonte(fonte)
    data_iso = data_em_formato_iso(data_publicacao)
    titulo_normalizado = normalizar_texto_basico(titulo)
    orgao_normalizado = normalizar_texto_basico(orgao)
    url_normalizada = normalizar_texto_basico(url)
    texto_normalizado = normalizar_texto_basico(texto_integral)

    hash_conteudo = gerar_hash_conteudo(
        fonte=fonte_normalizada,
        data_publicacao=data_iso,
        titulo=titulo_normalizado,
        orgao=orgao_normalizado,
        url=url_normalizada,
        texto_integral=texto_normalizado,
    )

    id_publicacao = gerar_id_publicacao(
        fonte=fonte_normalizada,
        data_publicacao=data_iso,
        titulo=titulo_normalizado,
        orgao=orgao_normalizado,
        url=url_normalizada,
        texto_integral=texto_normalizado,
    )

    publicacao = PublicacaoPadrao(
        id_publicacao=id_publicacao,
        fonte=fonte_normalizada,
        data_publicacao=data_iso,
        titulo=titulo_normalizado,
        orgao=orgao_normalizado,
        url=url_normalizada,
        texto_integral=texto_normalizado,
        secao=normalizar_texto_basico(secao),
        pagina=normalizar_texto_basico(pagina),
        tipo_publicacao=normalizar_texto_basico(tipo_publicacao),
        numero_processo=normalizar_texto_basico(numero_processo),
        palavras_chave_detectadas=palavras_chave_detectadas or [],
        metadados=metadados or {},
        data_coleta=datetime.now().isoformat(timespec="seconds"),
        hash_conteudo=hash_conteudo,
        origem_arquivo=normalizar_texto_basico(origem_arquivo),
        status_normalizacao=STATUS_NORMALIZACAO_OK,
    )

    validacao = publicacao.validar()

    if not validacao["valido"]:
        publicacao.status_normalizacao = STATUS_NORMALIZACAO_INVALIDA
    elif validacao["avisos"]:
        publicacao.status_normalizacao = STATUS_NORMALIZACAO_INCOMPLETA

    return publicacao


# ============================================================
# ADAPTADOR INICIAL PARA DOU
# ============================================================

def normalizar_publicacao_dou(
    publicacao_dou: Dict[str, Any],
    data_publicacao_padrao: Any = "",
    origem_arquivo: Any = "",
) -> PublicacaoPadrao:
    """
    Converte uma publicação atual do DOU para o contrato padrão.

    Esta função é propositalmente tolerante com nomes de campos,
    porque os arquivos atuais do DOU podem ter pequenas variações
    conforme etapa de extração/base.

    Importante:
    - não altera o pipeline atual;
    - serve apenas como ponte inicial para validar o contrato multi-fonte.
    """

    data_publicacao = (
        publicacao_dou.get("data_publicacao")
        or publicacao_dou.get("data")
        or publicacao_dou.get("data_execucao")
        or data_publicacao_padrao
    )

    titulo = (
        publicacao_dou.get("titulo")
        or publicacao_dou.get("title")
        or publicacao_dou.get("nome")
        or ""
    )

    orgao = (
        publicacao_dou.get("orgao")
        or publicacao_dou.get("órgão")
        or publicacao_dou.get("entidade")
        or publicacao_dou.get("ministerio")
        or ""
    )

    url = (
        publicacao_dou.get("url")
        or publicacao_dou.get("link")
        or publicacao_dou.get("href")
        or ""
    )

    texto_integral = (
        publicacao_dou.get("texto_integral")
        or publicacao_dou.get("texto")
        or publicacao_dou.get("conteudo")
        or publicacao_dou.get("texto_publicacao")
        or ""
    )

    secao = (
        publicacao_dou.get("secao")
        or publicacao_dou.get("seção")
        or publicacao_dou.get("secao_dou")
        or ""
    )

    pagina = (
        publicacao_dou.get("pagina")
        or publicacao_dou.get("página")
        or publicacao_dou.get("page")
        or ""
    )

    tipo_publicacao = (
        publicacao_dou.get("tipo_publicacao")
        or publicacao_dou.get("tipo")
        or ""
    )

    numero_processo = (
        publicacao_dou.get("numero_processo")
        or publicacao_dou.get("processo")
        or publicacao_dou.get("n_processo")
        or publicacao_dou.get("nr_processo")
        or ""
    )

    metadados = {
        "fonte_original": "dou",
        "id_original": publicacao_dou.get("id") or publicacao_dou.get("id_publicacao") or "",
        "dados_originais_disponiveis": sorted(list(publicacao_dou.keys())),
    }

    return construir_publicacao_padrao(
        fonte="dou",
        data_publicacao=data_publicacao,
        titulo=titulo,
        orgao=orgao,
        url=url,
        texto_integral=texto_integral,
        secao=secao,
        pagina=pagina,
        tipo_publicacao=tipo_publicacao,
        numero_processo=numero_processo,
        palavras_chave_detectadas=[],
        metadados=metadados,
        origem_arquivo=origem_arquivo,
    )


def normalizar_lista_publicacoes_dou(
    publicacoes_dou: List[Dict[str, Any]],
    data_publicacao_padrao: Any = "",
    origem_arquivo: Any = "",
) -> List[Dict[str, Any]]:
    """
    Converte uma lista de publicações DOU para lista de dicionários
    no contrato padrão.

    Retorna lista de dicts para facilitar gravação futura em JSON.
    """
    publicacoes_padrao: List[Dict[str, Any]] = []

    for publicacao in publicacoes_dou:
        publicacao_padrao = normalizar_publicacao_dou(
            publicacao_dou=publicacao,
            data_publicacao_padrao=data_publicacao_padrao,
            origem_arquivo=origem_arquivo,
        )

        publicacoes_padrao.append(publicacao_padrao.to_dict())

    return publicacoes_padrao


# ============================================================
# DOCUMENTAÇÃO TÉCNICA DO CONTRATO
# ============================================================

def obter_documentacao_contrato_publicacao() -> Dict[str, Any]:
    """
    Retorna a documentação técnica do contrato em formato estruturado.

    Pode ser usado futuramente por API, front, testes ou documentação.
    """
    return {
        "nome": "Contrato Padrão de Publicação Multi-Fonte",
        "versao": "1.0",
        "objetivo": (
            "Padronizar publicações de diferentes fontes para reaproveitar "
            "match, auditoria, relatório, consolidação e futuras APIs."
        ),
        "campos_obrigatorios": CAMPOS_OBRIGATORIOS_PUBLICACAO_PADRAO,
        "campos_opcionais": CAMPOS_OPCIONAIS_PUBLICACAO_PADRAO,
        "exemplo": {
            "id_publicacao": "dou_2026_05_14_a1b2c3d4e5f6",
            "fonte": "dou",
            "data_publicacao": "2026-05-14",
            "titulo": "Portaria nº 123, de 14 de maio de 2026",
            "orgao": "Ministério Exemplo",
            "url": "https://www.in.gov.br/...",
            "texto_integral": "Texto completo da publicação...",
            "secao": "1",
            "pagina": "25",
            "tipo_publicacao": "Portaria",
            "numero_processo": "00000.000000/2026-00",
            "palavras_chave_detectadas": [],
            "metadados": {
                "fonte_original": "dou"
            },
            "data_coleta": "2026-05-14T08:30:00",
            "hash_conteudo": "hash_sha256",
            "origem_arquivo": "backend/data/dou/base/base_publicacoes_2026-05-14.json",
            "status_normalizacao": "OK",
        },
        "regras": [
            "Toda publicação precisa ter fonte, data, título, órgão e texto integral.",
            "A fonte deve ser normalizada em minúsculo, sem espaços e sem caracteres especiais.",
            "A data_publicacao deve usar formato YYYY-MM-DD.",
            "O id_publicacao deve ser técnico, estável e rastreável.",
            "O hash_conteudo deve apoiar auditoria, deduplicação e reprocessamento.",
            "Campos específicos de uma fonte devem ficar dentro de metadados.",
            "O contrato não deve depender exclusivamente do DOU.",
        ],
    }