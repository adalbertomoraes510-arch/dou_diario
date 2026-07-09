# ============================================================
# SERVICE — Envio de E-mail
# Projeto Informativos / DOU
# ============================================================
#
# Responsabilidade:
# - Enviar e-mails HTML com ou sem anexo.
# - Carregar automaticamente o arquivo .env da raiz do projeto.
# - Usar variáveis de ambiente para autenticação.
# - Usar variáveis de ambiente para destinatários.
# - Permitir modo simulação para evitar disparo acidental.
# - Bloquear envio real quando não houver destinatário configurado.
#
# Este service NÃO executa DOU.
# Este service NÃO monta regra de negócio do dou_diario.
# Ele apenas envia e-mail.
# ============================================================

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable


# ============================================================
# CARGA DO .ENV
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]
DOTENV_PATH = ROOT_DIR / ".env"


def _carregar_dotenv_basico(caminho: Path, sobrescrever: bool = True) -> bool:
    """
    Carregador simples de .env para evitar dependência obrigatória.

    Suporta linhas no formato:
    CHAVE=valor

    Linhas vazias e comentários iniciados por # são ignorados.
    """
    if not caminho.exists():
        return False

    with caminho.open("r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()

            if not linha or linha.startswith("#") or "=" not in linha:
                continue

            chave, valor = linha.split("=", 1)
            chave = chave.strip()
            valor = valor.strip().strip('"').strip("'")

            if not chave:
                continue

            if sobrescrever or chave not in os.environ:
                os.environ[chave] = valor

    return True


def carregar_variaveis_ambiente() -> dict:
    """
    Carrega o arquivo .env da raiz do projeto.

    Regra:
    - o .env do projeto é a fonte principal de configuração;
    - valores do .env sobrescrevem variáveis antigas do Windows/PowerShell;
    - se python-dotenv estiver instalado, usa load_dotenv;
    - se não estiver instalado, usa carregador básico interno.
    """
    carregado = False
    origem = None

    try:
        from dotenv import load_dotenv  # type: ignore

        carregado = load_dotenv(
            dotenv_path=DOTENV_PATH,
            override=True,
        )
        origem = "python-dotenv"
    except Exception:
        carregado = _carregar_dotenv_basico(
            caminho=DOTENV_PATH,
            sobrescrever=True,
        )
        origem = "carregador_basico"

    return {
        "dotenv_path": str(DOTENV_PATH),
        "dotenv_existe": DOTENV_PATH.exists(),
        "dotenv_carregado": bool(carregado),
        "origem": origem,
    }


INFO_DOTENV = carregar_variaveis_ambiente()


# ============================================================
# CONFIGURAÇÃO SMTP
# ============================================================

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "30"))

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# Por segurança, o padrão é simulação.
# Para envio real:
# EMAIL_MODO_SIMULACAO=false
EMAIL_MODO_SIMULACAO = (
    os.getenv("EMAIL_MODO_SIMULACAO", "true")
    .strip()
    .lower()
    in {"1", "true", "sim", "yes", "s"}
)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def _normalizar_destinatarios(
    destinatarios: str | Iterable[str] | None,
) -> list[str]:
    """
    Normaliza destinatários recebidos como:
    - None
    - string separada por vírgula/ponto e vírgula
    - lista/tupla/set de strings

    Regra de segurança:
    - se destinatarios=None, usa somente EMAIL_DESTINATARIOS;
    - se EMAIL_DESTINATARIOS não estiver configurado, retorna lista vazia;
    - não existem destinatários fixos no código.
    """

    if destinatarios is None:
        env_destinatarios = os.getenv("EMAIL_DESTINATARIOS", "").strip()

        if not env_destinatarios:
            return []

        destinatarios = env_destinatarios

    if isinstance(destinatarios, str):
        partes = (
            destinatarios
            .replace(";", ",")
            .split(",")
        )

        return [
            email.strip()
            for email in partes
            if email.strip()
        ]

    return [
        str(email).strip()
        for email in destinatarios
        if str(email).strip()
    ]


def _normalizar_anexos(
    anexo: str | Path | None = None,
    anexos: Iterable[str | Path] | None = None,
) -> list[Path]:
    caminhos: list[Path] = []

    if anexo:
        caminhos.append(Path(anexo))

    if anexos:
        for item in anexos:
            if item:
                caminhos.append(Path(item))

    return caminhos


def _criar_mensagem_email(
    assunto: str,
    corpo_html: str,
    destinatarios: list[str],
    corpo_texto: str | None = None,
    anexo: str | Path | None = None,
    anexos: Iterable[str | Path] | None = None,
) -> EmailMessage:
    if not assunto or not assunto.strip():
        raise ValueError("Assunto do e-mail não informado.")

    if not corpo_html or not corpo_html.strip():
        raise ValueError("Corpo HTML do e-mail não informado.")

    if not destinatarios:
        raise ValueError("Lista de destinatários vazia.")

    msg = EmailMessage()
    msg["From"] = EMAIL_USER or "email_nao_configurado"
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto.strip()

    texto_fallback = (
        corpo_texto
        if corpo_texto
        else "Seu cliente de e-mail não suporta HTML."
    )

    msg.set_content(texto_fallback)
    msg.add_alternative(corpo_html, subtype="html")

    caminhos_anexos = _normalizar_anexos(
        anexo=anexo,
        anexos=anexos,
    )

    for caminho in caminhos_anexos:
        if not caminho.exists():
            raise FileNotFoundError(f"Anexo não encontrado: {caminho}")

        content_type, _ = mimetypes.guess_type(str(caminho))

        if content_type:
            maintype, subtype = content_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        with caminho.open("rb") as arquivo:
            msg.add_attachment(
                arquivo.read(),
                maintype=maintype,
                subtype=subtype,
                filename=caminho.name,
            )

    return msg


def validar_configuracao_email(
    modo_simulacao: bool | None = None,
    destinatarios: str | Iterable[str] | None = None,
) -> dict:
    """
    Valida a configuração de envio.

    Em modo simulação, EMAIL_USER e EMAIL_PASS não são obrigatórios.
    Em envio real, são obrigatórios.
    """

    modo = EMAIL_MODO_SIMULACAO if modo_simulacao is None else modo_simulacao

    lista_destinatarios = _normalizar_destinatarios(destinatarios)

    resultado = {
        "dotenv": INFO_DOTENV,
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "smtp_timeout": SMTP_TIMEOUT,
        "email_user_configurado": bool(EMAIL_USER),
        "email_pass_configurado": bool(EMAIL_PASS),
        "modo_simulacao": modo,
        "destinatarios": lista_destinatarios,
        "configuracao_valida": True,
        "erros": [],
    }

    if not lista_destinatarios:
        resultado["erros"].append(
            "Nenhum destinatário configurado. Defina EMAIL_DESTINATARIOS "
            "ou informe destinatarios explicitamente na chamada."
        )

    if not modo:
        if not EMAIL_USER:
            resultado["erros"].append("Variável de ambiente EMAIL_USER não definida.")

        if not EMAIL_PASS:
            resultado["erros"].append("Variável de ambiente EMAIL_PASS não definida.")

    resultado["configuracao_valida"] = not resultado["erros"]

    return resultado


# ============================================================
# FUNÇÃO PRINCIPAL DE ENVIO
# ============================================================

def enviar_email(
    assunto: str,
    corpo_html: str,
    anexo: str | Path | None = None,
    anexos: Iterable[str | Path] | None = None,
    destinatarios: str | Iterable[str] | None = None,
    corpo_texto: str | None = None,
    modo_simulacao: bool | None = None,
) -> dict:
    """
    Envia e-mail HTML com anexo opcional.

    Compatibilidade:
    - Mantém assinatura básica do programa antigo:
      enviar_email(assunto, corpo_html, anexo=None)

    Novos recursos:
    - múltiplos anexos
    - destinatários customizados
    - corpo texto fallback
    - modo simulação
    - retorno estruturado
    """

    modo = EMAIL_MODO_SIMULACAO if modo_simulacao is None else modo_simulacao

    lista_destinatarios = _normalizar_destinatarios(destinatarios)

    config = validar_configuracao_email(
        modo_simulacao=modo,
        destinatarios=destinatarios,
    )

    if not config["configuracao_valida"]:
        raise RuntimeError(
            "Configuração de e-mail inválida: "
            + " | ".join(config["erros"])
        )

    msg = _criar_mensagem_email(
        assunto=assunto,
        corpo_html=corpo_html,
        corpo_texto=corpo_texto,
        destinatarios=lista_destinatarios,
        anexo=anexo,
        anexos=anexos,
    )

    caminhos_anexos = _normalizar_anexos(
        anexo=anexo,
        anexos=anexos,
    )

    resultado = {
        "status": "SIMULADO" if modo else "ENVIADO",
        "modo_simulacao": modo,
        "dotenv": INFO_DOTENV,
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "email_origem": EMAIL_USER,
        "destinatarios": lista_destinatarios,
        "assunto": assunto,
        "anexos": [str(caminho) for caminho in caminhos_anexos],
    }

    if modo:
        print("=" * 80)
        print("SIMULAÇÃO DE ENVIO DE E-MAIL")
        print("=" * 80)
        print(f"Assunto: {assunto}")
        print(f"Arquivo .env: {INFO_DOTENV.get('dotenv_path')}")
        print(f".env carregado: {INFO_DOTENV.get('dotenv_carregado')}")
        print(f"Origem: {EMAIL_USER or 'EMAIL_USER não configurado'}")
        print(f"Destinatários: {', '.join(lista_destinatarios)}")

        if caminhos_anexos:
            print("Anexos:")
            for caminho in caminhos_anexos:
                print(f"- {caminho}")
        else:
            print("Anexos: nenhum")

        print("Nenhum e-mail foi enviado.")
        print("=" * 80)

        return resultado

    with smtplib.SMTP(
        SMTP_SERVER,
        SMTP_PORT,
        timeout=SMTP_TIMEOUT,
    ) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)

    print("=" * 80)
    print("E-MAIL ENVIADO COM SUCESSO")
    print("=" * 80)
    print(f"Assunto: {assunto}")
    print(f"Arquivo .env: {INFO_DOTENV.get('dotenv_path')}")
    print(f".env carregado: {INFO_DOTENV.get('dotenv_carregado')}")
    print(f"Destinatários: {', '.join(lista_destinatarios)}")
    print("=" * 80)

    return resultado


# ============================================================
# ALIAS EXPLÍCITO
# ============================================================

def enviar_email_html(
    assunto: str,
    corpo_html: str,
    anexo: str | Path | None = None,
    anexos: Iterable[str | Path] | None = None,
    destinatarios: str | Iterable[str] | None = None,
    corpo_texto: str | None = None,
    modo_simulacao: bool | None = None,
) -> dict:
    return enviar_email(
        assunto=assunto,
        corpo_html=corpo_html,
        anexo=anexo,
        anexos=anexos,
        destinatarios=destinatarios,
        corpo_texto=corpo_texto,
        modo_simulacao=modo_simulacao,
    )