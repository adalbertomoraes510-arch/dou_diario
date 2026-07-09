# ============================================================
# MODELO — Boletim Informativo / Curadoria Mensal
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Definir o contrato técnico do pré-boletim informativo.
#
# Este arquivo cria a estrutura oficial para transformar publicações
# relevantes da finalidade "informativos" em um boletim mensal/período
# com curadoria automática e apoio posterior de IA.
#
# Este arquivo NÃO altera:
# - busca DOU;
# - extração;
# - base auditável;
# - match_service.py;
# - orquestrador;
# - envio de e-mail;
# - camada operacional DOU.
# ============================================================

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


# ============================================================
# CONSTANTES — FINALIDADE
# ============================================================

FINALIDADE_INFORMATIVOS = "informativos"


# ============================================================
# CONSTANTES — NÍVEL DE RELEVÂNCIA
# ============================================================

RELEVANCIA_ALTA = "ALTA"
RELEVANCIA_MEDIA = "MEDIA"
RELEVANCIA_BAIXA = "BAIXA"
RELEVANCIA_DESCARTADO = "DESCARTADO"

NIVEIS_RELEVANCIA_VALIDOS = [
    RELEVANCIA_ALTA,
    RELEVANCIA_MEDIA,
    RELEVANCIA_BAIXA,
    RELEVANCIA_DESCARTADO,
]


# ============================================================
# CONSTANTES — CLASSIFICAÇÃO DE RELAÇÃO COM LEROY / PRODUTOS
# ============================================================

RELACAO_DIRETA_LEROY = "RELACAO_DIRETA_LEROY"
PRODUTO_COMERCIALIZADO = "PRODUTO_COMERCIALIZADO"
CERTIFICACAO_SEGURANCA_CONFORMIDADE = "CERTIFICACAO_SEGURANCA_CONFORMIDADE"
IMPORTACAO_COMERCIO_REGULACAO = "IMPORTACAO_COMERCIO_REGULACAO"
ORGAO_REGULADOR_RELEVANTE = "ORGAO_REGULADOR_RELEVANTE"
MONITORAMENTO_SETORIAL = "MONITORAMENTO_SETORIAL"
DESCARTADO_SEM_RELACAO_MATERIAL = "DESCARTADO_SEM_RELACAO_MATERIAL"
OUTROS_ASSUNTOS = "OUTROS_ASSUNTOS"

CLASSIFICACOES_RELACAO_VALIDAS = [
    RELACAO_DIRETA_LEROY,
    PRODUTO_COMERCIALIZADO,
    CERTIFICACAO_SEGURANCA_CONFORMIDADE,
    IMPORTACAO_COMERCIO_REGULACAO,
    ORGAO_REGULADOR_RELEVANTE,
    MONITORAMENTO_SETORIAL,
    DESCARTADO_SEM_RELACAO_MATERIAL,
    OUTROS_ASSUNTOS,
]


# ============================================================
# CONSTANTES — SEÇÕES DO BOLETIM
# ============================================================

SECAO_RESUMO_EXECUTIVO = "RESUMO_EXECUTIVO"
SECAO_PUBLICACOES_DIRETAS_LEROY = "PUBLICACOES_DIRETAS_LEROY"
SECAO_PRODUTOS_COMERCIALIZADOS = "PRODUTOS_COMERCIALIZADOS"
SECAO_NORMAS_CERTIFICACOES_SEGURANCA = "NORMAS_CERTIFICACOES_SEGURANCA"
SECAO_IMPORTACAO_COMERCIO_REGULACAO = "IMPORTACAO_COMERCIO_REGULACAO"
SECAO_ORGAOS_REGULADORES = "ORGAOS_REGULADORES"
SECAO_MONITORAMENTO_SETORIAL = "MONITORAMENTO_SETORIAL"
SECAO_ITENS_DESCARTADOS = "ITENS_DESCARTADOS"
SECAO_RECOMENDACOES = "RECOMENDACOES_ACOMPANHAMENTO"

SECOES_BOLETIM_VALIDAS = [
    SECAO_RESUMO_EXECUTIVO,
    SECAO_PUBLICACOES_DIRETAS_LEROY,
    SECAO_PRODUTOS_COMERCIALIZADOS,
    SECAO_NORMAS_CERTIFICACOES_SEGURANCA,
    SECAO_IMPORTACAO_COMERCIO_REGULACAO,
    SECAO_ORGAOS_REGULADORES,
    SECAO_MONITORAMENTO_SETORIAL,
    SECAO_ITENS_DESCARTADOS,
    SECAO_RECOMENDACOES,
]


# ============================================================
# CONSTANTES — STATUS
# ============================================================

STATUS_BOLETIM_RASCUNHO = "RASCUNHO"
STATUS_BOLETIM_PRE_CURADO = "PRE_CURADO"
STATUS_BOLETIM_AGUARDANDO_REVISAO_IA = "AGUARDANDO_REVISAO_IA"
STATUS_BOLETIM_REVISADO_IA = "REVISADO_IA"
STATUS_BOLETIM_APROVADO = "APROVADO"

STATUS_BOLETIM_VALIDOS = [
    STATUS_BOLETIM_RASCUNHO,
    STATUS_BOLETIM_PRE_CURADO,
    STATUS_BOLETIM_AGUARDANDO_REVISAO_IA,
    STATUS_BOLETIM_REVISADO_IA,
    STATUS_BOLETIM_APROVADO,
]


# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def normalizar_texto_basico(valor: Any) -> str:
    """
    Normaliza texto para uso em campos do boletim.
    """
    if valor is None:
        return ""

    texto = str(valor).strip()
    texto = re.sub(r"\s+", " ", texto)

    return texto


def normalizar_chave(valor: Any) -> str:
    """
    Normaliza texto para chaves técnicas.
    """
    texto = normalizar_texto_basico(valor).lower()
    texto = texto.replace("-", "_")
    texto = texto.replace("/", "_")
    texto = texto.replace(" ", "_")
    texto = re.sub(r"[^a-z0-9_]", "", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")

    return texto


def data_em_formato_iso(valor: Any) -> str:
    """
    Converte data para YYYY-MM-DD quando possível.
    """
    if valor is None:
        return ""

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")

    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")

    texto = normalizar_texto_basico(valor)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return texto

    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", texto):
        try:
            return datetime.strptime(texto, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return texto

    return texto


def validar_data_iso(valor: str) -> bool:
    """
    Valida formato YYYY-MM-DD.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor or ""):
        return False

    try:
        datetime.strptime(valor, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def gerar_hash_curadoria(*valores: Any) -> str:
    """
    Gera hash técnico para rastreabilidade da curadoria.
    """
    texto_base = "|".join(
        normalizar_texto_basico(valor).lower()
        for valor in valores
    )

    return hashlib.sha256(texto_base.encode("utf-8")).hexdigest()


def gerar_id_item_boletim(
    id_publicacao: Any,
    fonte: Any,
    data_publicacao: Any,
    classificacao_relacao: Any,
    titulo: Any,
) -> str:
    """
    Gera ID técnico para item curado do boletim.
    """
    fonte_norm = normalizar_chave(fonte) or "fonte"
    data_norm = data_em_formato_iso(data_publicacao).replace("-", "_") or "data"
    classificacao_norm = normalizar_chave(classificacao_relacao) or "classificacao"

    hash_item = gerar_hash_curadoria(
        id_publicacao,
        fonte,
        data_publicacao,
        classificacao_relacao,
        titulo,
    )[:12]

    return f"item_boletim_{fonte_norm}_{data_norm}_{classificacao_norm}_{hash_item}"


def gerar_id_boletim(
    finalidade: Any,
    data_inicio: Any,
    data_fim: Any,
    escopo: Any = "periodo",
) -> str:
    """
    Gera ID técnico do boletim.
    """
    finalidade_norm = normalizar_chave(finalidade) or FINALIDADE_INFORMATIVOS
    escopo_norm = normalizar_chave(escopo) or "periodo"

    inicio = data_em_formato_iso(data_inicio).replace("-", "_")
    fim = data_em_formato_iso(data_fim).replace("-", "_")

    hash_boletim = gerar_hash_curadoria(
        finalidade_norm,
        inicio,
        fim,
        escopo_norm,
    )[:10]

    return f"boletim_{finalidade_norm}_{escopo_norm}_{inicio}_a_{fim}_{hash_boletim}"


def texto_curto(texto: Any, limite: int = 500) -> str:
    """
    Limita texto para campos de resumo.
    """
    valor = normalizar_texto_basico(texto)

    if len(valor) <= limite:
        return valor

    return valor[: limite - 3].rstrip() + "..."


# ============================================================
# MODELO — ITEM CURADO
# ============================================================

@dataclass
class ItemBoletimInformativo:
    """
    Representa uma publicação curada para o boletim informativo.
    """

    id_item: str
    id_publicacao: str
    fonte: str
    data_publicacao: str
    titulo: str
    orgao: str
    url: str

    secao_boletim: str
    classificacao_relacao: str
    nivel_relevancia: str

    resumo_tecnico: str = ""
    motivo_relevancia: str = ""
    tema: str = ""
    produto_assunto: str = ""
    risco_oportunidade: str = ""
    recomendacao_acompanhamento: str = ""

    texto_referencia: str = ""
    palavras_chave_detectadas: List[str] = field(default_factory=list)
    evidencias: List[str] = field(default_factory=list)

    status_curadoria: str = STATUS_BOLETIM_RASCUNHO
    descartado: bool = False
    motivo_descarte: str = ""

    metadados: Dict[str, Any] = field(default_factory=dict)

    def validar(self) -> Dict[str, Any]:
        erros: List[str] = []
        avisos: List[str] = []

        if not normalizar_texto_basico(self.id_item):
            erros.append("Campo obrigatório ausente: id_item")

        if not normalizar_texto_basico(self.id_publicacao):
            avisos.append("Campo id_publicacao vazio. Item pode perder rastreabilidade.")

        if not normalizar_texto_basico(self.fonte):
            erros.append("Campo obrigatório ausente: fonte")

        if not normalizar_texto_basico(self.data_publicacao):
            erros.append("Campo obrigatório ausente: data_publicacao")
        elif not validar_data_iso(self.data_publicacao):
            erros.append("Campo data_publicacao deve estar no formato YYYY-MM-DD")

        if not normalizar_texto_basico(self.titulo):
            erros.append("Campo obrigatório ausente: titulo")

        if not normalizar_texto_basico(self.orgao):
            avisos.append("Campo orgao vazio.")

        if self.secao_boletim not in SECOES_BOLETIM_VALIDAS:
            erros.append(f"Seção inválida: {self.secao_boletim}")

        if self.classificacao_relacao not in CLASSIFICACOES_RELACAO_VALIDAS:
            erros.append(f"Classificação de relação inválida: {self.classificacao_relacao}")

        if self.nivel_relevancia not in NIVEIS_RELEVANCIA_VALIDOS:
            erros.append(f"Nível de relevância inválido: {self.nivel_relevancia}")

        if self.status_curadoria not in STATUS_BOLETIM_VALIDOS:
            erros.append(f"Status de curadoria inválido: {self.status_curadoria}")

        if self.descartado and not normalizar_texto_basico(self.motivo_descarte):
            avisos.append("Item descartado sem motivo_descarte preenchido.")

        if self.nivel_relevancia != RELEVANCIA_DESCARTADO and not self.motivo_relevancia:
            avisos.append("Item relevante sem motivo_relevancia preenchido.")

        return {
            "valido": len(erros) == 0,
            "erros": erros,
            "avisos": avisos,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id_item": self.id_item,
            "id_publicacao": self.id_publicacao,
            "fonte": self.fonte,
            "data_publicacao": self.data_publicacao,
            "titulo": self.titulo,
            "orgao": self.orgao,
            "url": self.url,
            "secao_boletim": self.secao_boletim,
            "classificacao_relacao": self.classificacao_relacao,
            "nivel_relevancia": self.nivel_relevancia,
            "resumo_tecnico": self.resumo_tecnico,
            "motivo_relevancia": self.motivo_relevancia,
            "tema": self.tema,
            "produto_assunto": self.produto_assunto,
            "risco_oportunidade": self.risco_oportunidade,
            "recomendacao_acompanhamento": self.recomendacao_acompanhamento,
            "texto_referencia": self.texto_referencia,
            "palavras_chave_detectadas": self.palavras_chave_detectadas,
            "evidencias": self.evidencias,
            "status_curadoria": self.status_curadoria,
            "descartado": self.descartado,
            "motivo_descarte": self.motivo_descarte,
            "metadados": self.metadados,
        }

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "ItemBoletimInformativo":
        return cls(
            id_item=normalizar_texto_basico(dados.get("id_item")),
            id_publicacao=normalizar_texto_basico(dados.get("id_publicacao")),
            fonte=normalizar_chave(dados.get("fonte")),
            data_publicacao=data_em_formato_iso(dados.get("data_publicacao")),
            titulo=normalizar_texto_basico(dados.get("titulo")),
            orgao=normalizar_texto_basico(dados.get("orgao")),
            url=normalizar_texto_basico(dados.get("url")),
            secao_boletim=normalizar_texto_basico(dados.get("secao_boletim")),
            classificacao_relacao=normalizar_texto_basico(
                dados.get("classificacao_relacao")
            ),
            nivel_relevancia=normalizar_texto_basico(dados.get("nivel_relevancia")),
            resumo_tecnico=normalizar_texto_basico(dados.get("resumo_tecnico")),
            motivo_relevancia=normalizar_texto_basico(dados.get("motivo_relevancia")),
            tema=normalizar_texto_basico(dados.get("tema")),
            produto_assunto=normalizar_texto_basico(dados.get("produto_assunto")),
            risco_oportunidade=normalizar_texto_basico(
                dados.get("risco_oportunidade")
            ),
            recomendacao_acompanhamento=normalizar_texto_basico(
                dados.get("recomendacao_acompanhamento")
            ),
            texto_referencia=normalizar_texto_basico(dados.get("texto_referencia")),
            palavras_chave_detectadas=dados.get("palavras_chave_detectadas") or [],
            evidencias=dados.get("evidencias") or [],
            status_curadoria=normalizar_texto_basico(
                dados.get("status_curadoria")
            ) or STATUS_BOLETIM_RASCUNHO,
            descartado=bool(dados.get("descartado", False)),
            motivo_descarte=normalizar_texto_basico(dados.get("motivo_descarte")),
            metadados=dados.get("metadados") or {},
        )


# ============================================================
# MODELO — SEÇÃO DO BOLETIM
# ============================================================

@dataclass
class SecaoBoletimInformativo:
    """
    Representa uma seção do boletim final.
    """

    codigo: str
    titulo: str
    descricao: str = ""
    itens: List[ItemBoletimInformativo] = field(default_factory=list)

    def total_itens(self) -> int:
        return len(self.itens)

    def total_relevantes(self) -> int:
        return len([item for item in self.itens if not item.descartado])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codigo": self.codigo,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "total_itens": self.total_itens(),
            "total_relevantes": self.total_relevantes(),
            "itens": [item.to_dict() for item in self.itens],
        }


# ============================================================
# MODELO — RESUMO EXECUTIVO
# ============================================================

@dataclass
class ResumoExecutivoBoletim:
    """
    Resume os principais achados do boletim.
    """

    periodo: str
    total_publicacoes_analisadas: int = 0
    total_itens_curados: int = 0
    total_relevancia_alta: int = 0
    total_relevancia_media: int = 0
    total_relevancia_baixa: int = 0
    total_descartados: int = 0

    principais_temas: List[str] = field(default_factory=list)
    principais_orgaos: List[str] = field(default_factory=list)
    principais_produtos_assuntos: List[str] = field(default_factory=list)

    sintese_executiva: str = ""
    conclusao: str = ""
    recomendacoes_gerais: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "periodo": self.periodo,
            "total_publicacoes_analisadas": self.total_publicacoes_analisadas,
            "total_itens_curados": self.total_itens_curados,
            "total_relevancia_alta": self.total_relevancia_alta,
            "total_relevancia_media": self.total_relevancia_media,
            "total_relevancia_baixa": self.total_relevancia_baixa,
            "total_descartados": self.total_descartados,
            "principais_temas": self.principais_temas,
            "principais_orgaos": self.principais_orgaos,
            "principais_produtos_assuntos": self.principais_produtos_assuntos,
            "sintese_executiva": self.sintese_executiva,
            "conclusao": self.conclusao,
            "recomendacoes_gerais": self.recomendacoes_gerais,
        }


# ============================================================
# MODELO — BOLETIM INFORMATIVO
# ============================================================

@dataclass
class BoletimInformativo:
    """
    Contrato principal do boletim informativo.
    """

    id_boletim: str
    finalidade: str
    data_inicio: str
    data_fim: str

    titulo: str
    status: str = STATUS_BOLETIM_RASCUNHO

    resumo_executivo: ResumoExecutivoBoletim = field(
        default_factory=lambda: ResumoExecutivoBoletim(periodo="")
    )

    secoes: List[SecaoBoletimInformativo] = field(default_factory=list)
    itens_curados: List[ItemBoletimInformativo] = field(default_factory=list)

    prompt_ia: str = ""
    observacoes_curadoria: List[str] = field(default_factory=list)
    arquivos_origem: List[str] = field(default_factory=list)
    arquivos_saida: Dict[str, str] = field(default_factory=dict)
    metadados: Dict[str, Any] = field(default_factory=dict)

    criado_em: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    atualizado_em: str = ""

    def validar(self) -> Dict[str, Any]:
        erros: List[str] = []
        avisos: List[str] = []

        if not normalizar_texto_basico(self.id_boletim):
            erros.append("Campo obrigatório ausente: id_boletim")

        if not normalizar_texto_basico(self.finalidade):
            erros.append("Campo obrigatório ausente: finalidade")

        if not normalizar_texto_basico(self.data_inicio):
            erros.append("Campo obrigatório ausente: data_inicio")
        elif not validar_data_iso(self.data_inicio):
            erros.append("Campo data_inicio deve estar no formato YYYY-MM-DD")

        if not normalizar_texto_basico(self.data_fim):
            erros.append("Campo obrigatório ausente: data_fim")
        elif not validar_data_iso(self.data_fim):
            erros.append("Campo data_fim deve estar no formato YYYY-MM-DD")

        if self.status not in STATUS_BOLETIM_VALIDOS:
            erros.append(f"Status inválido: {self.status}")

        if not self.itens_curados:
            avisos.append("Boletim sem itens curados.")

        for indice, item in enumerate(self.itens_curados, start=1):
            validacao_item = item.validar()

            if not validacao_item["valido"]:
                erros.append(
                    f"Item {indice} inválido: {validacao_item['erros']}"
                )

        return {
            "valido": len(erros) == 0,
            "erros": erros,
            "avisos": avisos,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id_boletim": self.id_boletim,
            "finalidade": self.finalidade,
            "data_inicio": self.data_inicio,
            "data_fim": self.data_fim,
            "titulo": self.titulo,
            "status": self.status,
            "resumo_executivo": self.resumo_executivo.to_dict(),
            "secoes": [secao.to_dict() for secao in self.secoes],
            "itens_curados": [item.to_dict() for item in self.itens_curados],
            "prompt_ia": self.prompt_ia,
            "observacoes_curadoria": self.observacoes_curadoria,
            "arquivos_origem": self.arquivos_origem,
            "arquivos_saida": self.arquivos_saida,
            "metadados": self.metadados,
            "criado_em": self.criado_em,
            "atualizado_em": self.atualizado_em,
        }


# ============================================================
# CONSTRUTORES PADRONIZADOS
# ============================================================

def construir_item_boletim(
    id_publicacao: Any,
    fonte: Any,
    data_publicacao: Any,
    titulo: Any,
    orgao: Any,
    url: Any,
    secao_boletim: str,
    classificacao_relacao: str,
    nivel_relevancia: str,
    resumo_tecnico: Any = "",
    motivo_relevancia: Any = "",
    tema: Any = "",
    produto_assunto: Any = "",
    risco_oportunidade: Any = "",
    recomendacao_acompanhamento: Any = "",
    texto_referencia: Any = "",
    palavras_chave_detectadas: Optional[List[str]] = None,
    evidencias: Optional[List[str]] = None,
    descartado: bool = False,
    motivo_descarte: Any = "",
    metadados: Optional[Dict[str, Any]] = None,
) -> ItemBoletimInformativo:
    """
    Cria item curado padronizado para o boletim.
    """
    data_iso = data_em_formato_iso(data_publicacao)

    id_item = gerar_id_item_boletim(
        id_publicacao=id_publicacao,
        fonte=fonte,
        data_publicacao=data_iso,
        classificacao_relacao=classificacao_relacao,
        titulo=titulo,
    )

    status_curadoria = STATUS_BOLETIM_PRE_CURADO

    if descartado or nivel_relevancia == RELEVANCIA_DESCARTADO:
        descartado = True
        nivel_relevancia = RELEVANCIA_DESCARTADO
        classificacao_relacao = DESCARTADO_SEM_RELACAO_MATERIAL
        secao_boletim = SECAO_ITENS_DESCARTADOS

    return ItemBoletimInformativo(
        id_item=id_item,
        id_publicacao=normalizar_texto_basico(id_publicacao),
        fonte=normalizar_chave(fonte),
        data_publicacao=data_iso,
        titulo=normalizar_texto_basico(titulo),
        orgao=normalizar_texto_basico(orgao),
        url=normalizar_texto_basico(url),
        secao_boletim=secao_boletim,
        classificacao_relacao=classificacao_relacao,
        nivel_relevancia=nivel_relevancia,
        resumo_tecnico=texto_curto(resumo_tecnico, limite=1000),
        motivo_relevancia=texto_curto(motivo_relevancia, limite=1000),
        tema=normalizar_texto_basico(tema),
        produto_assunto=normalizar_texto_basico(produto_assunto),
        risco_oportunidade=texto_curto(risco_oportunidade, limite=1000),
        recomendacao_acompanhamento=texto_curto(
            recomendacao_acompanhamento,
            limite=1000,
        ),
        texto_referencia=texto_curto(texto_referencia, limite=3000),
        palavras_chave_detectadas=palavras_chave_detectadas or [],
        evidencias=evidencias or [],
        status_curadoria=status_curadoria,
        descartado=descartado,
        motivo_descarte=normalizar_texto_basico(motivo_descarte),
        metadados=metadados or {},
    )


def construir_resumo_executivo(
    data_inicio: Any,
    data_fim: Any,
    itens_curados: List[ItemBoletimInformativo],
    total_publicacoes_analisadas: int = 0,
) -> ResumoExecutivoBoletim:
    """
    Monta resumo executivo inicial a partir dos itens curados.
    """
    inicio = data_em_formato_iso(data_inicio)
    fim = data_em_formato_iso(data_fim)
    periodo = f"{inicio} a {fim}"

    total_alta = len([
        item for item in itens_curados
        if item.nivel_relevancia == RELEVANCIA_ALTA
    ])

    total_media = len([
        item for item in itens_curados
        if item.nivel_relevancia == RELEVANCIA_MEDIA
    ])

    total_baixa = len([
        item for item in itens_curados
        if item.nivel_relevancia == RELEVANCIA_BAIXA
    ])

    total_descartados = len([
        item for item in itens_curados
        if item.descartado or item.nivel_relevancia == RELEVANCIA_DESCARTADO
    ])

    temas = sorted({
        item.tema
        for item in itens_curados
        if item.tema and not item.descartado
    })

    orgaos = sorted({
        item.orgao
        for item in itens_curados
        if item.orgao and not item.descartado
    })

    produtos = sorted({
        item.produto_assunto
        for item in itens_curados
        if item.produto_assunto and not item.descartado
    })

    total_relevantes = len([
        item for item in itens_curados
        if not item.descartado
    ])

    sintese = (
        f"No período de {periodo}, foram analisadas "
        f"{total_publicacoes_analisadas} publicação(ões). "
        f"A curadoria identificou {total_relevantes} item(ns) com potencial "
        f"relevância para acompanhamento e {total_descartados} item(ns) "
        f"descartado(s) por ausência de relação material."
    )

    conclusao = (
        "O boletim está em etapa de pré-curadoria e deve ser revisado antes "
        "da emissão final ao cliente."
    )

    return ResumoExecutivoBoletim(
        periodo=periodo,
        total_publicacoes_analisadas=total_publicacoes_analisadas,
        total_itens_curados=len(itens_curados),
        total_relevancia_alta=total_alta,
        total_relevancia_media=total_media,
        total_relevancia_baixa=total_baixa,
        total_descartados=total_descartados,
        principais_temas=temas,
        principais_orgaos=orgaos,
        principais_produtos_assuntos=produtos,
        sintese_executiva=sintese,
        conclusao=conclusao,
        recomendacoes_gerais=[
            "Validar os itens de maior relevância antes do boletim final.",
            "Confirmar se os temas classificados como setoriais possuem impacto prático para Leroy.",
            "Separar itens diretamente acionáveis de itens apenas informativos.",
        ],
    )


def agrupar_itens_em_secoes(
    itens_curados: List[ItemBoletimInformativo],
) -> List[SecaoBoletimInformativo]:
    """
    Agrupa itens por seção do boletim.
    """
    mapa_titulos = {
        SECAO_PUBLICACOES_DIRETAS_LEROY: "Publicações diretamente relacionadas à Leroy",
        SECAO_PRODUTOS_COMERCIALIZADOS: "Produtos comercializados",
        SECAO_NORMAS_CERTIFICACOES_SEGURANCA: "Normas, certificações, segurança e conformidade",
        SECAO_IMPORTACAO_COMERCIO_REGULACAO: "Importação, comércio e regulação",
        SECAO_ORGAOS_REGULADORES: "Órgãos reguladores relevantes",
        SECAO_MONITORAMENTO_SETORIAL: "Monitoramento setorial",
        SECAO_ITENS_DESCARTADOS: "Itens descartados ou sem relação material",
        SECAO_RECOMENDACOES: "Recomendações de acompanhamento",
    }

    mapa_descricoes = {
        SECAO_PUBLICACOES_DIRETAS_LEROY: "Itens com menção direta à Leroy ou relação explícita.",
        SECAO_PRODUTOS_COMERCIALIZADOS: "Itens relacionados a produtos potencialmente comercializados pela Leroy.",
        SECAO_NORMAS_CERTIFICACOES_SEGURANCA: "Itens sobre certificação, segurança, conformidade, qualidade ou requisitos técnicos.",
        SECAO_IMPORTACAO_COMERCIO_REGULACAO: "Itens sobre importação, comércio, fiscalização, licenças ou regulação econômica.",
        SECAO_ORGAOS_REGULADORES: "Itens publicados por órgãos reguladores relevantes para acompanhamento.",
        SECAO_MONITORAMENTO_SETORIAL: "Itens sem relação direta, mas úteis para leitura de ambiente regulatório.",
        SECAO_ITENS_DESCARTADOS: "Itens excluídos da narrativa principal por ausência de relação material.",
        SECAO_RECOMENDACOES: "Recomendações operacionais ou pontos de atenção derivados da curadoria.",
    }

    secoes: List[SecaoBoletimInformativo] = []

    for codigo in SECOES_BOLETIM_VALIDAS:
        if codigo in [SECAO_RESUMO_EXECUTIVO]:
            continue

        itens_secao = [
            item
            for item in itens_curados
            if item.secao_boletim == codigo
        ]

        if not itens_secao:
            continue

        secoes.append(
            SecaoBoletimInformativo(
                codigo=codigo,
                titulo=mapa_titulos.get(codigo, codigo),
                descricao=mapa_descricoes.get(codigo, ""),
                itens=itens_secao,
            )
        )

    return secoes


def construir_prompt_ia_boletim(
    boletim: BoletimInformativo,
) -> str:
    """
    Gera prompt pronto para IA revisar a curadoria e redigir boletim final.
    """
    linhas: List[str] = []

    linhas.append("Você é uma IA apoiando a revisão de um boletim regulatório mensal.")
    linhas.append("")
    linhas.append("Objetivo:")
    linhas.append(
        "Revisar os itens pré-curados e montar um boletim executivo claro, "
        "objetivo e confiável para acompanhamento de publicações oficiais "
        "relacionadas à Leroy, produtos comercializados, certificações, "
        "segurança, conformidade, importação, comércio e regulação."
    )
    linhas.append("")
    linhas.append("Regras importantes:")
    linhas.append("- Não invente fatos.")
    linhas.append("- Use somente as informações dos itens fornecidos.")
    linhas.append("- Separe relação direta de simples monitoramento setorial.")
    linhas.append("- Destaque itens acionáveis.")
    linhas.append("- Informe quando um item for apenas acompanhamento preventivo.")
    linhas.append("- Preserve órgão, data e link quando disponíveis.")
    linhas.append("")
    linhas.append(f"Período: {boletim.data_inicio} a {boletim.data_fim}")
    linhas.append(f"Total de itens curados: {len(boletim.itens_curados)}")
    linhas.append("")
    linhas.append("Estrutura esperada do boletim final:")
    linhas.append("1. Resumo executivo do período")
    linhas.append("2. Publicações diretamente relacionadas à Leroy")
    linhas.append("3. Produtos comercializados / temas de produto")
    linhas.append("4. Normas, certificações, segurança e conformidade")
    linhas.append("5. Importação, comércio e regulação")
    linhas.append("6. Monitoramento setorial")
    linhas.append("7. Itens descartados ou sem relação material")
    linhas.append("8. Recomendações de acompanhamento")
    linhas.append("")
    linhas.append("Itens pré-curados:")

    for indice, item in enumerate(boletim.itens_curados, start=1):
        linhas.append("")
        linhas.append(f"Item {indice}")
        linhas.append(f"- Data: {item.data_publicacao}")
        linhas.append(f"- Fonte: {item.fonte}")
        linhas.append(f"- Órgão: {item.orgao}")
        linhas.append(f"- Título: {item.titulo}")
        linhas.append(f"- Link: {item.url}")
        linhas.append(f"- Seção sugerida: {item.secao_boletim}")
        linhas.append(f"- Classificação: {item.classificacao_relacao}")
        linhas.append(f"- Relevância: {item.nivel_relevancia}")
        linhas.append(f"- Tema: {item.tema}")
        linhas.append(f"- Produto/assunto: {item.produto_assunto}")
        linhas.append(f"- Motivo da relevância: {item.motivo_relevancia}")
        linhas.append(f"- Resumo técnico: {item.resumo_tecnico}")
        linhas.append(f"- Recomendação: {item.recomendacao_acompanhamento}")

        if item.descartado:
            linhas.append(f"- Motivo do descarte: {item.motivo_descarte}")

    linhas.append("")
    linhas.append("Tarefa:")
    linhas.append(
        "Monte o boletim final em linguagem executiva, com tom técnico, "
        "objetivo e adequado para envio ao cliente."
    )

    return "\n".join(linhas)


def construir_boletim_informativo(
    data_inicio: Any,
    data_fim: Any,
    itens_curados: List[ItemBoletimInformativo],
    total_publicacoes_analisadas: int = 0,
    finalidade: str = FINALIDADE_INFORMATIVOS,
    titulo: str = "",
    arquivos_origem: Optional[List[str]] = None,
    metadados: Optional[Dict[str, Any]] = None,
) -> BoletimInformativo:
    """
    Cria boletim informativo padronizado.
    """
    inicio = data_em_formato_iso(data_inicio)
    fim = data_em_formato_iso(data_fim)

    id_boletim = gerar_id_boletim(
        finalidade=finalidade,
        data_inicio=inicio,
        data_fim=fim,
        escopo="periodo",
    )

    if not titulo:
        titulo = f"Pré-boletim Informativo — {inicio} a {fim}"

    resumo = construir_resumo_executivo(
        data_inicio=inicio,
        data_fim=fim,
        itens_curados=itens_curados,
        total_publicacoes_analisadas=total_publicacoes_analisadas,
    )

    secoes = agrupar_itens_em_secoes(itens_curados)

    boletim = BoletimInformativo(
        id_boletim=id_boletim,
        finalidade=finalidade,
        data_inicio=inicio,
        data_fim=fim,
        titulo=titulo,
        status=STATUS_BOLETIM_AGUARDANDO_REVISAO_IA,
        resumo_executivo=resumo,
        secoes=secoes,
        itens_curados=itens_curados,
        prompt_ia="",
        observacoes_curadoria=[
            "Boletim gerado em etapa de pré-curadoria automática.",
            "Recomenda-se revisão humana ou assistida por IA antes do envio final.",
        ],
        arquivos_origem=arquivos_origem or [],
        arquivos_saida={},
        metadados=metadados or {},
    )

    boletim.prompt_ia = construir_prompt_ia_boletim(boletim)

    return boletim


# ============================================================
# DOCUMENTAÇÃO DO CONTRATO
# ============================================================

def obter_documentacao_boletim_informativo() -> Dict[str, Any]:
    """
    Retorna documentação técnica do contrato do boletim.
    """
    return {
        "nome": "Contrato do Boletim Informativo",
        "versao": "1.0",
        "objetivo": (
            "Padronizar a curadoria de publicações da finalidade informativos "
            "para geração de pré-boletim mensal ou por período."
        ),
        "modelos": [
            "ItemBoletimInformativo",
            "SecaoBoletimInformativo",
            "ResumoExecutivoBoletim",
            "BoletimInformativo",
        ],
        "niveis_relevancia": NIVEIS_RELEVANCIA_VALIDOS,
        "classificacoes_relacao": CLASSIFICACOES_RELACAO_VALIDAS,
        "secoes_boletim": SECOES_BOLETIM_VALIDAS,
        "status_boletim": STATUS_BOLETIM_VALIDOS,
        "fluxo_recomendado": [
            "Ler relatórios diários ou consolidado mensal da finalidade informativos.",
            "Identificar publicações realmente relevantes.",
            "Classificar por relação com Leroy, produto, certificação, segurança, comércio ou regulação.",
            "Descartar itens sem relação material.",
            "Gerar pré-boletim JSON/TXT.",
            "Gerar prompt para IA revisar e redigir boletim final.",
            "Validar antes do envio ao cliente.",
        ],
    }