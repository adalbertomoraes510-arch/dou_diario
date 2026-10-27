
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
    """Consulta somente leitura: usa a grade e as provas reais do executor."""
    pasta, grade = caminhos(dia)
    arquivo_grade = reg.caminho_dia(dia, grade)
    resumo_arquivo = pasta / 'resumo_execucao.json'

    if not arquivo_grade.is_file():
        return {
            'data': dia, 'gerado': False, 'enviado': False,
            'envio_pendente': False, 'reenviavel': False,
            'concluir_disponivel': False, 'reprocessavel': True,
            'cobertura_completa': False, 'mensagem':
            'Nenhuma pesquisa registrada para esta data. Execute o monitoramento.'
        }

    completo = False
    modalidade = 'NAO_COMPROVADA'
    try:
        _, completo, linhas, _ = runner.preparar_relatorio_email(dia, grade, reg)
        origens = [(origem, ref) for _, fonte, _, origem, _, _, ref in linhas if fonte == 'DOU']
        _, modalidade = runner._modalidade_email(grade, origens)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        motivo = 'Falha ao validar cobertura: ' + str(exc)[:180]
    else:
        motivo = ''

    enviado = False
    pendente = False
    controles = pasta / 'email_operacional'
    if controles.is_dir():
        for comprovante in controles.glob('*.json'):
            try:
                registro = json.loads(comprovante.read_text(encoding='utf-8-sig'))
                if registro.get('data') != dia:
                    continue
                status = registro.get('status')
                if status == 'ENVIADO':
                    enviado = True
                elif status in ('ENVIO_INICIADO', 'ENVIO_INDETERMINADO'):
                    pendente = True
            except (OSError, ValueError, TypeError):
                pendente = True

    # Nao liberar novas mensagens para uma data com envio confirmado.
    # Casos de envio indeterminado exigem verificacao manual antes do reenvio.
    try:
        configurado = bool(runner.configuracao_email_prod())
    except (OSError, RuntimeError, ValueError):
        configurado = False
    concluir = bool(completo and configurado and not pendente and not enviado)
    reprocessavel = not completo and not pendente

    if pendente:
        mensagem = 'Envio indeterminado ou iniciado: verificar comprovante antes de nova tentativa.'
    elif enviado:
        mensagem = 'Email de ' + dia + ' ja enviado. Novo envio automatico bloqueado.'
    elif completo and not configurado:
        mensagem = 'Pesquisas completas; envio PROD nao habilitado.'
    elif completo:
        mensagem = 'Pesquisas completas (' + modalidade + '). Concluir e enviar email sem repetir pesquisas.'
    else:
        mensagem = motivo or 'Cobertura incompleta. Reprocessar somente as atividades pendentes.'

    return {
        'data': dia, 'gerado': arquivo_grade.is_file(),
        'resumo_disponivel': resumo_arquivo.is_file(),
        'enviado': enviado, 'envio_pendente': pendente,
        'reenviavel': concluir, 'concluir_disponivel': concluir,
        'reprocessavel': reprocessavel, 'cobertura_completa': bool(completo),
        'modalidade': modalidade, 'mensagem': mensagem
    }


def reenviar(dia):
    """Conclui envio pendente usando controle idempotente oficial, sem pesquisas."""
    with runner.bloquear_execucao_concorrente():
        estado = situacao(dia)
        if not estado['concluir_disponivel']:
            raise RuntimeError(estado['mensagem'])
        _, grade = caminhos(dia)
        resultado = runner.enviar_relatorio_operacional_dev(dia, grade, reg)
        status = str(resultado.get('status') or '')
        print('STATUS_EMAIL:', status, flush=True)
        if resultado.get('comprovante'):
            print('COMPROVANTE:', resultado['comprovante'], flush=True)
        return 0 if status == 'ENVIADO' else 3


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
