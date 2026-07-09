# ============================================================
# RUNNER — Diagnóstico da Estrutura do Projeto
# Projeto: Informativos
# ============================================================
#
# Objetivo:
# Gerar um diagnóstico estrutural do backend para entender:
#
# - Como o programa está organizado
# - Quais runners existem
# - Quais services existem
# - Quais models existem
# - Quais drivers existem
# - Quem importa quem
# - Quais arquivos parecem oficiais
# - Quais arquivos parecem testes/diagnósticos
#
# Este runner NÃO altera nenhum arquivo do sistema operacional.
# Ele apenas lê a estrutura e grava relatórios em:
#
# backend/data/diagnosticos/estrutura_projeto/
# ============================================================

from __future__ import annotations

import ast
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# CONFIGURAÇÃO
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"

SAIDA_DIR = (
    BACKEND_DIR
    / "data"
    / "diagnosticos"
    / "estrutura_projeto"
)

PASTAS_ANALISADAS = [
    "runners",
    "services",
    "drivers",
    "models",
    "config",
    "orquestradores",
    "core",
    "utils",
]

PASTAS_IGNORADAS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    "venv",
    "node_modules",
}

EXTENSOES_CODIGO = {
    ".py",
    ".json",
    ".txt",
    ".xlsx",
    ".csv",
    ".md",
}


# ============================================================
# MODELOS
# ============================================================

@dataclass
class ArquivoInfo:
    caminho: str
    caminho_relativo: str
    nome: str
    extensao: str
    pasta_raiz: str
    tamanho_bytes: int
    modificado_em: str
    linhas: Optional[int]
    tipo_arquivo: str
    perfil_sugerido: str
    observacao: str


@dataclass
class ImportInfo:
    arquivo_origem: str
    modulo_origem: str
    linha: int
    tipo_import: str
    modulo_importado: str
    item_importado: str


@dataclass
class DefinicaoInfo:
    arquivo: str
    modulo: str
    linha: int
    tipo: str
    nome: str


# ============================================================
# UTILITÁRIOS
# ============================================================

def agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def caminho_relativo(caminho: Path) -> str:
    try:
        return str(caminho.resolve().relative_to(ROOT_DIR)).replace("\\", "/")
    except Exception:
        return str(caminho).replace("\\", "/")


def garantir_saida() -> None:
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)


def deve_ignorar(caminho: Path) -> bool:
    partes = set(caminho.parts)
    return any(pasta in partes for pasta in PASTAS_IGNORADAS)


def modulo_python(caminho: Path) -> str:
    rel = caminho.resolve().relative_to(ROOT_DIR).with_suffix("")
    return ".".join(rel.parts)


def contar_linhas(caminho: Path) -> Optional[int]:
    if caminho.suffix.lower() != ".py":
        return None

    try:
        return len(caminho.read_text(encoding="utf-8").splitlines())
    except Exception:
        return None


def classificar_tipo_arquivo(caminho: Path) -> str:
    rel = caminho_relativo(caminho).lower()
    nome = caminho.name.lower()

    if "/runners/" in rel:
        return "RUNNER"

    if "/services/" in rel:
        return "SERVICE"

    if "/drivers/" in rel:
        return "DRIVER"

    if "/models/" in rel:
        return "MODEL"

    if "/orquestradores/" in rel:
        return "ORQUESTRADOR"

    if "/config/" in rel:
        return "CONFIG"

    if "/core/" in rel:
        return "CORE"

    if "/utils/" in rel:
        return "UTIL"

    if nome.endswith(".json"):
        return "DADOS_JSON"

    if nome.endswith(".xlsx"):
        return "PLANILHA"

    if nome.endswith(".txt"):
        return "TEXTO"

    return "OUTRO"


def sugerir_perfil(caminho: Path) -> tuple[str, str]:
    """
    Sugere perfil do arquivo sem excluir nada automaticamente.

    Classificação:
    - OFICIAL_PROVAVEL
    - SUPORTE_DIAGNOSTICO
    - TESTE_VALIDACAO
    - REVISAO_MANUAL
    """
    rel = caminho_relativo(caminho).lower()
    nome = caminho.name.lower()

    marcadores_teste = [
        "teste",
        "test_",
        "_test",
        "validar",
        "validacao",
        "diagnostico",
        "debug",
        "sandbox",
        "tmp",
        "temporario",
        "backup",
        "old",
        "antigo",
    ]

    marcadores_suporte = [
        "status",
        "diagnostico",
        "mapeamento",
        "auditoria",
        "relatorio",
        "resumo",
    ]

    if any(marcador in nome for marcador in marcadores_teste):
        return (
            "TESTE_VALIDACAO",
            "Arquivo parece ser usado para teste, validação, diagnóstico ou apoio técnico.",
        )

    if any(marcador in rel for marcador in marcadores_suporte):
        return (
            "SUPORTE_DIAGNOSTICO",
            "Arquivo parece apoiar auditoria, status, relatório ou diagnóstico.",
        )

    tipo = classificar_tipo_arquivo(caminho)

    if tipo in {"RUNNER", "SERVICE", "DRIVER", "MODEL", "ORQUESTRADOR", "CORE"}:
        return (
            "OFICIAL_PROVAVEL",
            "Arquivo parece fazer parte da estrutura principal do sistema.",
        )

    return (
        "REVISAO_MANUAL",
        "Arquivo precisa de revisão manual para definir se é oficial, teste ou histórico.",
    )


def obter_pasta_raiz(caminho: Path) -> str:
    try:
        rel = caminho.resolve().relative_to(BACKEND_DIR)
        return rel.parts[0] if rel.parts else ""
    except Exception:
        return ""


# ============================================================
# INVENTÁRIO DE ARQUIVOS
# ============================================================

def listar_arquivos_backend() -> List[Path]:
    arquivos: List[Path] = []

    for caminho in BACKEND_DIR.rglob("*"):
        if not caminho.is_file():
            continue

        if deve_ignorar(caminho):
            continue

        if caminho.suffix.lower() not in EXTENSOES_CODIGO:
            continue

        arquivos.append(caminho)

    arquivos.sort(key=lambda p: caminho_relativo(p))

    return arquivos


def montar_inventario() -> List[ArquivoInfo]:
    inventario: List[ArquivoInfo] = []

    for arquivo in listar_arquivos_backend():
        stat = arquivo.stat()
        perfil, observacao = sugerir_perfil(arquivo)

        inventario.append(
            ArquivoInfo(
                caminho=str(arquivo),
                caminho_relativo=caminho_relativo(arquivo),
                nome=arquivo.name,
                extensao=arquivo.suffix.lower(),
                pasta_raiz=obter_pasta_raiz(arquivo),
                tamanho_bytes=stat.st_size,
                modificado_em=datetime.fromtimestamp(
                    stat.st_mtime
                ).isoformat(timespec="seconds"),
                linhas=contar_linhas(arquivo),
                tipo_arquivo=classificar_tipo_arquivo(arquivo),
                perfil_sugerido=perfil,
                observacao=observacao,
            )
        )

    return inventario


# ============================================================
# ANÁLISE DE PYTHON
# ============================================================

def carregar_ast(caminho: Path) -> Optional[ast.AST]:
    try:
        texto = caminho.read_text(encoding="utf-8")
        return ast.parse(texto)
    except Exception:
        return None


def extrair_imports(caminho: Path) -> List[ImportInfo]:
    if caminho.suffix.lower() != ".py":
        return []

    arvore = carregar_ast(caminho)
    if arvore is None:
        return []

    imports: List[ImportInfo] = []
    modulo_origem = modulo_python(caminho)
    arquivo_origem = caminho_relativo(caminho)

    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modulo = alias.name or ""
                if modulo.startswith("backend"):
                    imports.append(
                        ImportInfo(
                            arquivo_origem=arquivo_origem,
                            modulo_origem=modulo_origem,
                            linha=getattr(node, "lineno", 0),
                            tipo_import="import",
                            modulo_importado=modulo,
                            item_importado=alias.asname or "",
                        )
                    )

        elif isinstance(node, ast.ImportFrom):
            modulo = node.module or ""
            if modulo.startswith("backend"):
                for alias in node.names:
                    imports.append(
                        ImportInfo(
                            arquivo_origem=arquivo_origem,
                            modulo_origem=modulo_origem,
                            linha=getattr(node, "lineno", 0),
                            tipo_import="from",
                            modulo_importado=modulo,
                            item_importado=alias.name,
                        )
                    )

    return imports


def extrair_definicoes(caminho: Path) -> List[DefinicaoInfo]:
    if caminho.suffix.lower() != ".py":
        return []

    arvore = carregar_ast(caminho)
    if arvore is None:
        return []

    definicoes: List[DefinicaoInfo] = []
    modulo = modulo_python(caminho)
    arquivo = caminho_relativo(caminho)

    for node in ast.walk(arvore):
        if isinstance(node, ast.FunctionDef):
            definicoes.append(
                DefinicaoInfo(
                    arquivo=arquivo,
                    modulo=modulo,
                    linha=getattr(node, "lineno", 0),
                    tipo="funcao",
                    nome=node.name,
                )
            )

        elif isinstance(node, ast.AsyncFunctionDef):
            definicoes.append(
                DefinicaoInfo(
                    arquivo=arquivo,
                    modulo=modulo,
                    linha=getattr(node, "lineno", 0),
                    tipo="funcao_async",
                    nome=node.name,
                )
            )

        elif isinstance(node, ast.ClassDef):
            definicoes.append(
                DefinicaoInfo(
                    arquivo=arquivo,
                    modulo=modulo,
                    linha=getattr(node, "lineno", 0),
                    tipo="classe",
                    nome=node.name,
                )
            )

    return definicoes


def analisar_python() -> tuple[List[ImportInfo], List[DefinicaoInfo]]:
    imports: List[ImportInfo] = []
    definicoes: List[DefinicaoInfo] = []

    arquivos_py = [
        arquivo
        for arquivo in listar_arquivos_backend()
        if arquivo.suffix.lower() == ".py"
    ]

    for arquivo in arquivos_py:
        imports.extend(extrair_imports(arquivo))
        definicoes.extend(extrair_definicoes(arquivo))

    return imports, definicoes


# ============================================================
# ESTRUTURA EM ÁRVORE
# ============================================================

def gerar_arvore_texto() -> str:
    linhas: List[str] = []

    linhas.append("backend/")
    raiz = BACKEND_DIR

    def visitar(pasta: Path, prefixo: str = "") -> None:
        itens = [
            item for item in pasta.iterdir()
            if not deve_ignorar(item)
        ]

        itens.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        for indice, item in enumerate(itens):
            conector = "└── " if indice == len(itens) - 1 else "├── "
            linhas.append(f"{prefixo}{conector}{item.name}")

            if item.is_dir():
                novo_prefixo = prefixo + ("    " if indice == len(itens) - 1 else "│   ")
                visitar(item, novo_prefixo)

    visitar(raiz)

    return "\n".join(linhas)


# ============================================================
# RESUMOS
# ============================================================

def contar_por_chave(lista: List[Dict[str, Any]], chave: str) -> Dict[str, int]:
    resultado: Dict[str, int] = {}

    for item in lista:
        valor = str(item.get(chave) or "")
        resultado[valor] = resultado.get(valor, 0) + 1

    return dict(sorted(resultado.items(), key=lambda x: x[0]))


def montar_relacao_runner_imports(imports: List[ImportInfo]) -> List[Dict[str, Any]]:
    relacoes: List[Dict[str, Any]] = []

    for item in imports:
        if ".runners." not in item.modulo_origem:
            continue

        relacoes.append(
            {
                "runner": item.modulo_origem,
                "arquivo_runner": item.arquivo_origem,
                "modulo_importado": item.modulo_importado,
                "item_importado": item.item_importado,
                "linha": item.linha,
            }
        )

    return relacoes


def montar_resumo_texto(
    inventario: List[ArquivoInfo],
    imports: List[ImportInfo],
    definicoes: List[DefinicaoInfo],
) -> str:
    inventario_dict = [asdict(item) for item in inventario]
    imports_dict = [asdict(item) for item in imports]
    definicoes_dict = [asdict(item) for item in definicoes]

    por_tipo = contar_por_chave(inventario_dict, "tipo_arquivo")
    por_perfil = contar_por_chave(inventario_dict, "perfil_sugerido")
    por_pasta = contar_por_chave(inventario_dict, "pasta_raiz")

    runners = [
        item for item in inventario_dict
        if item["tipo_arquivo"] == "RUNNER"
    ]

    services = [
        item for item in inventario_dict
        if item["tipo_arquivo"] == "SERVICE"
    ]

    drivers = [
        item for item in inventario_dict
        if item["tipo_arquivo"] == "DRIVER"
    ]

    models = [
        item for item in inventario_dict
        if item["tipo_arquivo"] == "MODEL"
    ]

    linhas: List[str] = []

    linhas.append("=" * 80)
    linhas.append("DIAGNÓSTICO DA ESTRUTURA DO PROJETO INFORMATIVOS")
    linhas.append("=" * 80)
    linhas.append("")
    linhas.append(f"Gerado em: {agora_iso()}")
    linhas.append(f"Raiz do projeto: {ROOT_DIR}")
    linhas.append(f"Backend: {BACKEND_DIR}")
    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("RESUMO GERAL")
    linhas.append("-" * 80)
    linhas.append(f"Total de arquivos inventariados: {len(inventario)}")
    linhas.append(f"Total de imports internos backend.*: {len(imports)}")
    linhas.append(f"Total de funções/classes detectadas: {len(definicoes)}")
    linhas.append("")
    linhas.append("Por tipo de arquivo:")
    for chave, valor in por_tipo.items():
        linhas.append(f"- {chave}: {valor}")

    linhas.append("")
    linhas.append("Por perfil sugerido:")
    for chave, valor in por_perfil.items():
        linhas.append(f"- {chave}: {valor}")

    linhas.append("")
    linhas.append("Por pasta raiz:")
    for chave, valor in por_pasta.items():
        linhas.append(f"- {chave}: {valor}")

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("RUNNERS ENCONTRADOS")
    linhas.append("-" * 80)
    for item in runners:
        linhas.append(f"- {item['caminho_relativo']} | {item['perfil_sugerido']}")

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("SERVICES ENCONTRADOS")
    linhas.append("-" * 80)
    for item in services:
        linhas.append(f"- {item['caminho_relativo']} | {item['perfil_sugerido']}")

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("DRIVERS ENCONTRADOS")
    linhas.append("-" * 80)
    for item in drivers:
        linhas.append(f"- {item['caminho_relativo']} | {item['perfil_sugerido']}")

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("MODELS ENCONTRADOS")
    linhas.append("-" * 80)
    for item in models:
        linhas.append(f"- {item['caminho_relativo']} | {item['perfil_sugerido']}")

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("OBSERVAÇÃO IMPORTANTE")
    linhas.append("-" * 80)
    linhas.append(
        "A classificação de perfil é apenas uma sugestão automática. "
        "Nenhum arquivo deve ser apagado somente com base neste relatório."
    )
    linhas.append(
        "A relação 'quem chama quem' é baseada em imports estáticos. "
        "Depois será necessário validar o fluxo real pelos runners oficiais."
    )

    linhas.append("")
    linhas.append("=" * 80)
    linhas.append("FIM DO DIAGNÓSTICO")
    linhas.append("=" * 80)

    return "\n".join(linhas)


# ============================================================
# GRAVAÇÃO DE ARQUIVOS
# ============================================================

def salvar_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def salvar_txt(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with caminho.open("w", encoding="utf-8") as arquivo:
        arquivo.write(texto)


def salvar_csv(caminho: Path, linhas: List[Dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    if not linhas:
        with caminho.open("w", encoding="utf-8", newline="") as arquivo:
            arquivo.write("")
        return

    colunas = list(linhas[0].keys())

    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writeheader()
        writer.writerows(linhas)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar_diagnostico() -> Dict[str, Any]:
    garantir_saida()

    inventario = montar_inventario()
    imports, definicoes = analisar_python()

    inventario_dict = [asdict(item) for item in inventario]
    imports_dict = [asdict(item) for item in imports]
    definicoes_dict = [asdict(item) for item in definicoes]
    relacao_runners = montar_relacao_runner_imports(imports)

    resumo = {
        "gerado_em": agora_iso(),
        "root_dir": str(ROOT_DIR),
        "backend_dir": str(BACKEND_DIR),
        "saida_dir": str(SAIDA_DIR),
        "total_arquivos": len(inventario),
        "total_imports_backend": len(imports),
        "total_definicoes": len(definicoes),
        "total_relacoes_runner_imports": len(relacao_runners),
        "arquivos_por_tipo": contar_por_chave(inventario_dict, "tipo_arquivo"),
        "arquivos_por_perfil": contar_por_chave(inventario_dict, "perfil_sugerido"),
        "arquivos_por_pasta_raiz": contar_por_chave(inventario_dict, "pasta_raiz"),
    }

    payload_completo = {
        "resumo": resumo,
        "inventario": inventario_dict,
        "imports_backend": imports_dict,
        "definicoes": definicoes_dict,
        "relacao_runners_imports": relacao_runners,
    }

    salvar_json(SAIDA_DIR / "diagnostico_estrutura_completo.json", payload_completo)
    salvar_json(SAIDA_DIR / "resumo_estrutura.json", resumo)

    salvar_csv(SAIDA_DIR / "inventario_arquivos.csv", inventario_dict)
    salvar_csv(SAIDA_DIR / "imports_backend.csv", imports_dict)
    salvar_csv(SAIDA_DIR / "definicoes_python.csv", definicoes_dict)
    salvar_csv(SAIDA_DIR / "relacao_runners_imports.csv", relacao_runners)

    salvar_txt(SAIDA_DIR / "estrutura_backend_tree.txt", gerar_arvore_texto())
    salvar_txt(
        SAIDA_DIR / "resumo_estrutura_projeto.txt",
        montar_resumo_texto(inventario, imports, definicoes),
    )

    return {
        "status": "DIAGNOSTICO_GERADO_COM_SUCESSO",
        "saida_dir": caminho_relativo(SAIDA_DIR),
        "resumo": resumo,
        "arquivos_gerados": [
            caminho_relativo(SAIDA_DIR / "diagnostico_estrutura_completo.json"),
            caminho_relativo(SAIDA_DIR / "resumo_estrutura.json"),
            caminho_relativo(SAIDA_DIR / "inventario_arquivos.csv"),
            caminho_relativo(SAIDA_DIR / "imports_backend.csv"),
            caminho_relativo(SAIDA_DIR / "definicoes_python.csv"),
            caminho_relativo(SAIDA_DIR / "relacao_runners_imports.csv"),
            caminho_relativo(SAIDA_DIR / "estrutura_backend_tree.txt"),
            caminho_relativo(SAIDA_DIR / "resumo_estrutura_projeto.txt"),
        ],
    }


def main() -> None:
    print("=" * 80)
    print("DIAGNÓSTICO DA ESTRUTURA DO PROJETO")
    print("=" * 80)

    resultado = executar_diagnostico()

    print(f"Status: {resultado['status']}")
    print(f"Saída: {resultado['saida_dir']}")
    print("")
    print("Resumo:")
    for chave, valor in resultado["resumo"].items():
        print(f"- {chave}: {valor}")

    print("")
    print("Arquivos gerados:")
    for arquivo in resultado["arquivos_gerados"]:
        print(f"- {arquivo}")

    print("=" * 80)
    print("DIAGNÓSTICO FINALIZADO")
    print("=" * 80)


if __name__ == "__main__":
    main()