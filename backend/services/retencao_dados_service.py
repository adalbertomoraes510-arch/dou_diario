# ============================================================
# SERVICE — Retenção de Dados
# Remove arquivos antigos conforme política oficial do projeto
# ============================================================

import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT_DIR / "backend" / "data"

RETENCAO_DIAS = 90


def calcular_data_limite(
    data_referencia: datetime.date | None = None
) -> datetime.datetime:

    if data_referencia is None:
        data_referencia = datetime.date.today()

    data_limite = data_referencia - datetime.timedelta(
        days=RETENCAO_DIAS
    )

    return datetime.datetime.combine(
        data_limite,
        datetime.time.min
    )


def arquivo_deve_ser_removido(
    caminho: Path,
    data_limite: datetime.datetime
) -> bool:

    if not caminho.is_file():
        return False

    modificado_em = datetime.datetime.fromtimestamp(
        caminho.stat().st_mtime
    )

    return modificado_em < data_limite


def listar_arquivos_antigos(
    data_referencia: datetime.date | None = None
) -> list[Path]:

    data_limite = calcular_data_limite(data_referencia)

    if not DATA_DIR.exists():
        return []

    antigos = []

    for caminho in DATA_DIR.rglob("*"):
        if arquivo_deve_ser_removido(
            caminho=caminho,
            data_limite=data_limite
        ):
            antigos.append(caminho)

    return antigos


def limpar_arquivos_antigos(
    data_referencia: datetime.date | None = None,
    modo_simulacao: bool = True
) -> dict:

    data_limite = calcular_data_limite(data_referencia)
    arquivos = listar_arquivos_antigos(data_referencia)

    removidos = []
    erros = []

    for caminho in arquivos:

        item = {
            "arquivo": str(caminho),
            "modificado_em": datetime.datetime.fromtimestamp(
                caminho.stat().st_mtime
            ).isoformat(timespec="seconds")
        }

        if modo_simulacao:
            removidos.append(item)
            continue

        try:
            caminho.unlink()
            removidos.append(item)

        except Exception as e:
            erros.append({
                "arquivo": str(caminho),
                "erro": str(e)
            })

    return {
        "status": "SIMULACAO" if modo_simulacao else "EXECUTADO",
        "retencao_dias": RETENCAO_DIAS,
        "data_limite": data_limite.isoformat(timespec="seconds"),
        "total_encontrados": len(arquivos),
        "total_processados": len(removidos),
        "total_erros": len(erros),
        "arquivos": removidos,
        "erros": erros
    }