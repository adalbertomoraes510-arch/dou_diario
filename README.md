# DOU Diário — Automação INLABS / Diário Oficial da União

Sistema para processamento diário do Diário Oficial da União, com foco principal na finalidade `dou_diario`.

O sistema coleta publicações do DOU, aplica regras de palavras-chave e relevância, gera relatórios executivos, produz páginas de íntegra, publica essas íntegras no Cloudflare e envia o e-mail diário com os respectivos links.

Além do fluxo diário, o projeto possui monitoramento anual de números de processo no DOU e em documentos da Diretoria Colegiada da Anvisa.

---

## 1. Escopo funcional

### 1.1 Fluxo principal do DOU Diário

1. Coletar e processar as publicações do Diário Oficial da União.
2. Aplicar as regras de palavras-chave, match e relevância.
3. Gerar os dados intermediários da execução.
4. Gerar os relatórios de resultado.
5. Gerar as íntegras em HTML e TXT das publicações relevantes.
6. Publicar as íntegras no Cloudflare.
7. Enviar o e-mail diário com o resumo e o link **Ver íntegra**.

### 1.2 Monitoramento anual de processos

Ao final do DOU Diário, o sistema:

1. abre o arquivo `palavras_chave.xlsx`;
2. lê exclusivamente a aba `PROCESSOS`;
3. lê exclusivamente a coluna `PROCESSO`;
4. valida, normaliza e remove duplicidades;
5. pesquisa todos os processos atuais em todo o acervo anual disponível do DOU;
6. pesquisa os mesmos processos nas atas e pautas anuais da Dicol/Anvisa;
7. aplica OCR aos PDFs sem camada de texto;
8. atualiza os relatórios consolidados DOU + Anvisa.

A planilha é a fonte única da lista monitorada. Para incluir ou excluir um processo, altere apenas a coluna `PROCESSO`.

---

## 2. Ambientes

### DEV

```text
C:\Projetos_Automacao_BA\DOU_Diario_DEV
```

### PROD

```text
C:\Projetos_Automacao_BA\DOU_Diario_PROD
```

### Python / ambiente virtual

```text
C:\Projetos_Automacao_BA\venv\Scripts\python.exe
```

---

## 3. Comando principal

### DEV

```powershell
cd C:\Projetos_Automacao_BA\DOU_Diario_DEV

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m backend.runners.run_orquestrador_dou_periodo
```

### PROD

```powershell
cd C:\Projetos_Automacao_BA\DOU_Diario_PROD

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m backend.runners.run_orquestrador_dou_periodo
```

Com o ambiente virtual já ativo, também é possível usar:

```powershell
python -m backend.runners.run_orquestrador_dou_periodo
```

---

## 4. Estrutura principal

```text
backend/                         Código principal, configurações, drivers, runners e services
frontend/                        Arquivos de interface, quando aplicável
tests/                           Testes automatizados
docs/                            Documentação operacional
README.md                        Documentação geral do projeto
requirements.txt                 Dependências Python
.env.example                     Modelo de configuração por ambiente
.gitignore                       Regras do que não deve subir para o Git
.gitattributes                   Regras de tratamento dos arquivos no Git
publicar_integras_cloudflare.ps1 Script de publicação das íntegras no Cloudflare
```

Arquivos principais do monitoramento anual:

```text
backend/services/pesquisa_processos_dou_service.py
backend/runners/run_pesquisa_processos_dou_2026.py
backend/runners/run_orquestrador_dou_periodo.py
```

---

## 5. Palavras-chave e processos monitorados

Os arquivos de palavras-chave fazem parte da configuração e da regra de negócio do sistema.

Arquivo principal da finalidade `dou_diario`:

```text
backend/config/finalidades/dou_diario/palavras_chave.xlsx
```

Outros formatos possíveis:

```text
backend/config/finalidades/<finalidade>/palavras_chave.xlsx
backend/config/finalidades/<finalidade>/monitoramentos/<monitoramento>/palavras_chave.xlsx
```

Esses arquivos devem subir para o Git e ser promovidos para PROD.

Não devem subir arquivos temporários do Excel, como:

```text
~$palavras_chave.xlsx
```

### 5.1 Fonte única dos processos

No ambiente DEV:

```text
C:\Projetos_Automacao_BA\DOU_Diario_DEV\backend\config\finalidades\dou_diario\palavras_chave.xlsx
```

Configuração utilizada:

```text
Aba: PROCESSOS
Coluna: PROCESSO
```

Para o monitoramento anual, as demais colunas da planilha são ignoradas.

### 5.2 Regra de pesquisa

A pesquisa de processos é determinística:

- sem IA;
- sem similaridade;
- sem correspondência parcial;
- somente números completos de processo;
- validação de 17 dígitos;
- tolerância apenas para variações de pontuação e espaçamento;
- remoção de duplicidades da lista.

### 5.3 Escopo anual

Em cada execução, todos os processos atuais da planilha são pesquisados novamente em todo o acervo anual disponível.

Em 2026, a cobertura confirmada utilizada no INLABS começa em:

```text
23/03/2026
```

Portanto, o período de `01/01/2026` a `22/03/2026` não está coberto pela fonte INLABS atualmente utilizada.

---

## 6. Integração do monitoramento anual

O fluxo integrado executa:

```text
DOU Diário
→ leitura da coluna PROCESSO
→ pesquisa anual no DOU
→ consulta das atas da Anvisa
→ consulta das pautas da Anvisa
→ OCR dos PDFs sem texto
→ consolidação DOU + Anvisa
```

### 6.1 Reutilização de arquivos

O programa evita trabalho desnecessário:

```text
ZIP válido do DOU já baixado → reutilizado
PDF da Anvisa já baixado     → reutilizado
PDF já processado por OCR    → reutilizado
```

Mesmo reutilizando os arquivos locais, a pesquisa textual é refeita com a lista atual da planilha. Dessa forma, um processo incluído posteriormente também será procurado nos meses anteriores.

### 6.2 Isolamento de falhas

Uma falha no monitoramento anual não invalida o DOU Diário.

O sistema deve registrar separadamente:

```text
Status do DOU Diário
Status da pesquisa anual do DOU
Status da consulta Anvisa
Status do OCR
```

---

## 7. Arquivo `.env`

O arquivo `.env` não deve subir para o Git.

Cada ambiente deve possuir seu próprio arquivo:

```text
DOU_Diario_DEV\.env
DOU_Diario_PROD\.env
```

O arquivo versionado deve ser somente:

```text
.env.example
```

O `.env.example` serve como modelo e não deve conter senhas, tokens ou dados sensíveis reais.

Variáveis importantes:

```text
DOU_INTEGRA_BASE_URL
DOU_PUBLICAR_INTEGRAS_CLOUDFLARE
DOU_CLOUDFLARE_SCRIPT=publicar_integras_cloudflare.ps1
DOU_PUBLICAR_INTEGRAS_BLOQUEAR_EMAIL_SE_FALHAR
```

Em DEV, podem ser utilizados destinatários de teste.

Em PROD, devem ser utilizados somente os destinatários oficiais.

---

## 8. Dependências

Dependências Python relevantes:

```text
openpyxl
requests
beautifulsoup4
pypdf
ocrmypdf
```

Instalação no ambiente virtual:

```powershell
C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m pip install openpyxl requests beautifulsoup4 pypdf ocrmypdf
```

O OCR também depende de instalações externas no Windows:

```text
Tesseract OCR
Ghostscript
```

O idioma português precisa estar disponível no Tesseract com o código:

```text
por
```

Verificação:

```powershell
tesseract --list-langs
```

---

## 9. Dados gerados

A pasta abaixo é utilizada para os dados de execução:

```text
backend/data/dou/
```

Somente este arquivo deve permanecer versionado:

```text
backend/data/dou/.gitkeep
```

Não devem subir para o Git:

```text
backend/data/dou/base/
backend/data/dou/bruto/
backend/data/dou/auditoria/
backend/data/dou/match/
backend/data/dou/relatorios/
backend/data/dou/integras/
backend/data/dou/inlabs/
backend/data/dou/logs_execucao/
backend/data/dou/links_resolvidos/
backend/data/dou/cache/
backend/data/dou/tmp/
backend/data/dou/pesquisas/
backend/data/dou/periodos/
```

Essas pastas são recriadas durante as execuções.

### 9.1 Resultados do monitoramento anual

Os relatórios são gravados, por padrão, em:

```text
backend/data/dou/pesquisas/processos_2026/
```

Principais saídas:

```text
resultado_processos_2026.csv
resultado_processos_2026.json
resultado_processos_2026_resumo.txt

resultado_processos_anvisa_dicol_2026.csv
resultado_processos_anvisa_dicol_2026.json
resultado_processos_anvisa_dicol_2026_resumo.txt

resultado_processos_2026_todas_fontes.csv
resultado_processos_2026_todas_fontes.json
resultado_processos_2026_todas_fontes_resumo.txt
```

---

## 10. Publicação das íntegras

O script de publicação das íntegras no Cloudflare é:

```text
publicar_integras_cloudflare.ps1
```

Ele publica os arquivos gerados em:

```text
backend/data/dou/integras/
```

A URL base das íntegras é definida no `.env` pela variável:

```text
DOU_INTEGRA_BASE_URL
```

---

## 11. Validação antes de commit

Antes de versionar ou promover para PROD, execute:

```powershell
C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m py_compile .\backend\services\email_dou_diario_service.py

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m py_compile .\backend\services\dou_integra_html_service.py

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m py_compile .\backend\services\pesquisa_processos_dou_service.py

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m py_compile .\backend\runners\run_pesquisa_processos_dou_2026.py

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m py_compile .\backend\runners\run_orquestrador_dou_periodo.py

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m compileall -q .\backend
```

Se os comandos não exibirem erros, a sintaxe está válida.

---

## 12. Política de versionamento

### Deve subir para o Git

```text
backend/
frontend/
tests/
docs/
README.md
requirements.txt
.env.example
.gitignore
.gitattributes
publicar_integras_cloudflare.ps1
```

Os arquivos de configuração em `backend/config/finalidades/`, inclusive `palavras_chave.xlsx`, devem ser versionados.

### Não deve subir para o Git

```text
.env
backend/data/dou/*, exceto backend/data/dou/.gitkeep
cloudflare_deploy_dou_integras/
.wrangler/
wrangler.jsonc
__pycache__/
*.pyc
backup_*/
scripts temporários
arquivos de diagnóstico
arquivos gerados de execução
arquivos temporários do Excel iniciados por ~$
```

---

## 13. Promoção para PROD

Depois de clonar ou atualizar PROD via Git:

1. criar ou ajustar manualmente o `.env` do ambiente PROD;
2. confirmar as credenciais e variáveis operacionais;
3. confirmar que `palavras_chave.xlsx` contém a lista oficial;
4. instalar ou atualizar as dependências;
5. validar a sintaxe;
6. executar o orquestrador.

Comando:

```powershell
cd C:\Projetos_Automacao_BA\DOU_Diario_PROD

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m backend.runners.run_orquestrador_dou_periodo
```

---

## 14. Execução independente do monitoramento anual

O monitoramento anual também pode ser executado isoladamente:

```powershell
cd C:\Projetos_Automacao_BA\DOU_Diario_DEV

C:\Projetos_Automacao_BA\venv\Scripts\python.exe `
  -m backend.runners.run_pesquisa_processos_dou_2026
```

Essa execução usa a mesma planilha, as mesmas regras e os mesmos relatórios da execução integrada.
