
import argparse
import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path

from backend.runners import run_dia_integral_prod as runner
from backend.services import registro_pesquisa_diaria_fontes_service as reg


def caminhos(dia):
    dt.date.fromisoformat(dia)
    if runner.ROOT.name.casefold() != "dou_diario_prod":
        raise RuntimeError("Operacao permitida somente no PROD")

    pasta = (
        runner.ROOT
        / "backend/data/dou/pesquisas/processos_2026"
        / "monitoramento_diario_operacional"
        / dia
    )
    return pasta, pasta / "grade"


def situacao(dia):
    pasta, grade = caminhos(dia)

    comprovante = pasta / ("comprovante_relatorio_" + dia + ".json")
    relatorio = pasta / ("relatorio_diario_" + dia + ".txt")

    gerado = False
    if comprovante.is_file() and relatorio.is_file():
        try:
            prova = json.loads(comprovante.read_text(encoding="utf-8-sig"))
            hash_atual = hashlib.sha256(relatorio.read_bytes()).hexdigest()
            gerado = (
                prova.get("status") == "GERADO"
                and prova.get("sha256") == hash_atual
            )
        except (OSError, ValueError, TypeError):
            gerado = False

    enviado = False
    pendente = False
    pasta_email = pasta / "email_operacional"

    if pasta_email.is_dir():
        for arq in pasta_email.glob("*.json"):
            try:
                prova = json.loads(arq.read_text(encoding="utf-8-sig"))
                if prova.get("data") != dia:
                    continue

                status = prova.get("status")
                if status == "ENVIADO":
                    enviado = True
                    anexo = prova.get("anexo")
                    hash_anexo = prova.get("sha256_anexo")
                    if anexo and hash_anexo:
                        caminho_anexo = Path(anexo)
                        if caminho_anexo.is_file():
                            valido = (
                                hashlib.sha256(
                                    caminho_anexo.read_bytes()
                                ).hexdigest() == hash_anexo
                            )
                            gerado = gerado or valido

                if status in ("ENVIO_INICIADO", "ENVIO_INDETERMINADO"):
                    pendente = True

            except (OSError, ValueError, TypeError):
                pendente = True

    configurado = bool(runner.configuracao_email_prod())
    reenviavel = gerado and not pendente and configurado

    if pendente:
        mensagem = "Envio pendente de verificacao; reenvio bloqueado"
    elif not gerado:
        mensagem = "Relatorio ainda nao gerado para esta data"
    elif not configurado:
        mensagem = "Relatorio gerado; envio PROD nao habilitado"
    elif enviado:
        mensagem = "Relatorio gerado e ja enviado; reenvio disponivel"
    else:
        mensagem = "Relatorio gerado; envio manual disponivel"

    return {
        "data": dia,
        "gerado": gerado,
        "enviado": enviado,
        "envio_pendente": pendente,
        "reenviavel": reenviavel,
        "mensagem": mensagem
    }


def reenviar(dia):
    from backend.services.email_service import enviar_email

    with runner.bloquear_execucao_concorrente():
        estado = situacao(dia)
        if not estado["reenviavel"]:
            raise RuntimeError(estado["mensagem"])

        pasta, grade = caminhos(dia)
        destinatario = runner.configuracao_email_prod()

        resumo, completo, linhas, assinaturas = (
            runner.preparar_relatorio_email(dia, grade, reg)
        )

        if not completo:
            raise RuntimeError(
                "REENVIO BLOQUEADO: pesquisas obrigatorias incompletas."
            )

        assunto, texto, html = runner.montar_mensagem_email(
            dia, resumo, completo, linhas, grade
        )

        pasta_email = pasta / "email_operacional"
        pasta_email.mkdir(parents=True, exist_ok=True)

        identificador = (
            dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + "_"
            + uuid.uuid4().hex[:12]
        )

        anexo = pasta_email / ("relatorio_reenvio_" + identificador + ".txt")
        comprovante = pasta_email / ("reenvio_" + identificador + ".json")

        anexo.write_text(texto, encoding="utf-8")

        registro = {
            "tipo": "REENVIO_MANUAL",
            "data": dia,
            "identificador": identificador,
            "destinatarios": destinatario,
            "assunto": assunto,
            "anexo": str(anexo),
            "sha256_anexo": hashlib.sha256(
                anexo.read_bytes()
            ).hexdigest(),
            "status": "ENVIO_INICIADO",
            "iniciado_em": dt.datetime.now().isoformat(
                timespec="seconds"
            )
        }

        runner.guardar_atomico(comprovante, registro)

        try:
            resposta = enviar_email(
                assunto=assunto,
                corpo_html=html,
                corpo_texto=texto,
                anexo=anexo,
                destinatarios=destinatario,
                modo_simulacao=False
            )

            retorno = str(
                (resposta or {}).get("status") or ""
            ).upper()

            if retorno == "ENVIADO":
                registro["status"] = "ENVIADO"
                registro["confirmado_em"] = dt.datetime.now().isoformat(
                    timespec="seconds"
                )
                runner.guardar_atomico(comprovante, registro)
                print("REENVIO_MANUAL: ENVIADO", flush=True)
                print("COMPROVANTE:", comprovante, flush=True)
                return 0

            registro["status"] = "FALHA_ENVIO"
            registro["retorno_servico"] = retorno
            runner.guardar_atomico(comprovante, registro)
            print("REENVIO_MANUAL: FALHA_ENVIO", flush=True)
            return 3

        except Exception as erro:
            registro["status"] = "ENVIO_INDETERMINADO"
            registro["erro"] = str(erro)[:600]
            runner.guardar_atomico(comprovante, registro)
            print("REENVIO_MANUAL: ENVIO_INDETERMINADO", flush=True)
            return 4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--reenviar", action="store_true")
    args = parser.parse_args()

    if args.reenviar:
        return reenviar(args.data)

    print(json.dumps(situacao(args.data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
