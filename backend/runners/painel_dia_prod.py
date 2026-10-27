# -*- coding: utf-8 -*-
"""Painel local isolado DEV para executar o MESMO runner utilizado no terminal.

Nao altera o frontend existente. Nunca atende interfaces remotas. Apenas 127.0.0.1.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DEV = Path(__file__).resolve().parents[2]
PASTA = DEV / 'backend/runners'
HTML = PASTA/'painel_dia_prod.html'
LOGS = DEV/'backend/data/dou/pesquisas/processos_2026/monitoramento_diario_operacional/logs'
HOST = '127.0.0.1'
PORT = 8796
TRAVA = threading.Lock()
ATUAL = {'proc': None, 'log': None, 'data': None, 'comando': None, 'fluxo': None}


def _validar():
    if DEV.name.lower() != 'dou_diario_prod' or not HTML.is_file():
        raise RuntimeError('Bloqueado: arquivos do painel DEV nao encontrados')
    if not (PASTA/'run_dia_integral_prod.py').is_file():
        raise RuntimeError('Bloqueado: executor do DEV ausente')


def _data(valor):
    if not isinstance(valor,str) or not re.fullmatch(r'2026-\d{2}-\d{2}',valor):
        raise ValueError('Data invalida')
    d=dt.date.fromisoformat(valor)
    if d>dt.date.today() or d.weekday()>=5:
        raise ValueError('Selecione um dia util de 2026 nao futuro')
    return d.isoformat()


def _estado():
    with TRAVA:
        proc=ATUAL['proc']
        status=('NENHUMA_EXECUCAO' if proc is None else
                ('EM_EXECUCAO' if proc.poll() is None else ('CONCLUIDO' if proc.returncode==0 else 'ENCERRADO_COM_PENDENCIAS')))
        log=ATUAL['log']
        texto=''
        if isinstance(log,Path) and log.exists():
            # leitura limitada de log, sem arquivos confidenciais em cabecalhos
            with log.open('rb') as f:
                f.seek(max(0,log.stat().st_size-75000))
                texto=f.read().decode('utf-8','replace')[-50000:]
        return {'status':status,'data':ATUAL['data'], 'tipo':ATUAL['fluxo'],
                'codigo':proc.returncode if proc and proc.poll() is not None else None,
                'saida':texto}


class Handler(BaseHTTPRequestHandler):
    def _enviar(self,obj,codigo=200):
        b=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path=urlparse(self.path).path
        if path == "/api/situacao_relatorio":
            from urllib.parse import parse_qs
            from backend.runners import reenvio_manual_prod
            try:
                parametros = parse_qs(urlparse(self.path).query)
                dia = _data(parametros.get("data", [""])[0])
                self._enviar(reenvio_manual_prod.situacao(dia))
            except Exception as exc:
                self._enviar({"erro":str(exc)[:300]},400)
            return
        if path in ('/','/index.html'):
            b=HTML.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'unsafe-inline' 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(b)))
            self.end_headers();self.wfile.write(b)
        elif path=='/api/status': self._enviar(_estado())
        elif path=='/api/historico':
            from backend.runners.historico_operacional_prod import historico
            self._enviar(historico())
        else:self._enviar({'erro':'Recurso nao encontrado'},404)

    def _reenviar_relatorio(self):
        if self.headers.get("Origin","") != f"http://{HOST}:{PORT}":
            self._enviar({"erro":"Origem nao autorizada"},403)
            return

        try:
            tamanho=int(self.headers.get("Content-Length","0"))
            if tamanho<=0 or tamanho>2000:
                raise ValueError("JSON invalido")

            dados=json.loads(self.rfile.read(tamanho))
            dia=_data(dados.get("data"))

            if dados.get("confirmacao") != "CONCLUIR_EMAIL":
                raise ValueError("Confirmacao obrigatoria")

            from backend.runners import reenvio_manual_prod
            situacao=reenvio_manual_prod.situacao(dia)

            if not situacao["concluir_disponivel"]:
                self._enviar({"erro":situacao["mensagem"]},409)
                return

            with TRAVA:
                proc=ATUAL["proc"]
                if proc and proc.poll() is None:
                    self._enviar(
                        {"erro":"Ja existe processamento em andamento"},409
                    )
                    return

                LOGS.mkdir(parents=True,exist_ok=True)
                carimbo=dt.datetime.now().strftime(
                    "%Y%m%d_%H%M%S_%f"
                )
                arquivo=LOGS/f"{dia}_reenvio_{carimbo}.log"

                comando=[
                    sys.executable,"-u","-m",
                    "backend.runners.reenvio_manual_prod",
                    "--data",dia,"--reenviar"
                ]

                with arquivo.open("xb") as saida:
                    novo=subprocess.Popen(
                        comando,
                        cwd=str(DEV),
                        stdout=saida,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        creationflags=getattr(
                            subprocess,"CREATE_NO_WINDOW",0
                        ),
                        env={**os.environ,"PYTHONUNBUFFERED":"1"}
                    )

                ATUAL.update(
                    proc=novo,
                    log=arquivo,
                    data=dia,
                    comando=comando,
                    fluxo="envio"
                )

            self._enviar({
                "status":"INICIADO",
                "data":dia,
                "tipo":"envio"
            })

        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            self._enviar({"erro":str(exc)},400)
        except Exception as exc:
            self._enviar({"erro":str(exc)[:400]},500)

    def do_POST(self):
        if self.path == "/api/reenviar":
            self._reenviar_relatorio()
            return
        if self.path!='/api/executar':
            self._enviar({'erro':'Endpoint nao encontrado'},404);return
        # Protege contra chamada originada por outras paginas web locais/remotas
        if self.headers.get('Origin','') != f'http://{HOST}:{PORT}':
            self._enviar({'erro':'Origem da interface nao autorizada'},403);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>2000:raise ValueError('JSON invalido')
            dados=json.loads(self.rfile.read(size))
            data=_data(dados.get('data'))
            modo=dados.get('modo')
            if modo not in ('preflight','executar'):raise ValueError('Modo invalido')
            if modo == 'executar':
                from backend.runners import reenvio_manual_prod
                situacao = reenvio_manual_prod.situacao(data)
                if situacao.get('cobertura_completa'):
                    self._enviar({'erro':'Pesquisas completas. Use Concluir e enviar e-mail; nao repita pesquisas.'},409)
                    return
                if situacao.get('envio_pendente'):
                    self._enviar({'erro':'Envio indeterminado. Verifique antes de reprocessar.'},409)
                    return
            with TRAVA:
                proc=ATUAL['proc']
                if proc and proc.poll() is None:
                    self._enviar({'erro':'Ja existe um processamento em curso'},409);return
                # PRE-FLIGHT pode rodar via subprocesso tambem: sem escrita por parte do runner
                LOGS.mkdir(parents=True,exist_ok=True)
                carimbo=dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                arquivo=LOGS/f'{data}_{modo}_{carimbo}.log'
                comando=[sys.executable,'-u','-m','backend.runners.run_dia_integral_prod', '--data',data, '--preflight' if modo=='preflight' else '--executar']
                with arquivo.open('xb') as saida:
                    novo=subprocess.Popen(comando,cwd=str(DEV),stdout=saida,stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
                                          env={**os.environ,'PYTHONUNBUFFERED':'1'})
                ATUAL.update(proc=novo,log=arquivo,data=data,comando=comando,fluxo=modo)
            self._enviar({'status':'INICIADO','data':data,'tipo':modo})
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            self._enviar({'erro':str(exc)},400)
        except Exception as exc:
            self._enviar({'erro':'Nao foi possivel iniciar: '+str(exc)[:400]},500)

    def log_message(self,*args): pass


def main():
    _validar()
    print('PAINEL PROD:', f'http://{HOST}:{PORT}',flush=True)
    print('Painel PROD: comandos executam no ambiente PROD.',flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

if __name__=='__main__':main()
