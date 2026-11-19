# HaoYuan · 豪源

[简体中文](../../README.md) · [繁體中文](README.zh-TW.md) · [English](README.en.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [한국어](README.ko.md)  
[Français](README.fr.md) · [Español](README.es.md) · **Português (Brasil)** · [Italiano](README.it.md) · [Polski](README.pl.md) · [Todos os idiomas](README.md)

> Um estúdio pessoal de IA no qual você direciona vários funcionários de IA para trabalhar de forma assíncrona e em paralelo.  
> Um kernel, um conjunto de plugins instaláveis e um ciclo fechado verificável para tarefas de longo horizonte.

O HaoYuan foi reescrito sobre o **agent-harness**, usando-o como base de referência de backend. Ele preserva e fortalece a especialização em programação de um assistente de IA, ao mesmo tempo que reorganiza sessões, ferramentas, agentes, roteamento, habilidades, supervisão e orquestração em torno de uma arquitetura de plugins. O frontend foi totalmente reescrito, com o objetivo de elevar a "colaboração com IA" de uma janela de chat para uma bancada de trabalho que você pode direcionar, observar e na qual pode intervir.

![Bancada de trabalho](../screenshots/workbench-dark.png)

---

## 1. Funcionalidades principais

### 1.1 Um ciclo de codificação genuinamente utilizável

| Capacidade | Implementação |
|---|---|
| Reconhecimento do repositório | `project_scan`, `repo_map`, índice de símbolos, `search_symbol` |
| Leitura precisa | `read_file`, `read_range`, direcionamento por número de linha |
| Edições mínimas | `apply_patch` (diff unificado / SEARCH-REPLACE), `edit_file`, `multi_edit` |
| Operações de arquivo | `write_file`, `glob`, `grep`, `list_dir`, `delete_path`, `move_path` |
| Verificação de comandos | `run_shell` (UTF-8, timeouts, resumos estruturados de erros), wrapper `git` |
| Portão de verificação | Testes/lint/build são obrigatórios após alterações no código, impedindo "editar sem verificar" |
| Ciclo de teste e correção | Análise estruturada de falhas do pytest → localização de linha → correção mínima → escalonamento por impressão digital de falhas |
| Subagentes | `task` explora em um contexto isolado e retorna apenas conclusões, evitando a poluição do contexto principal |
| Governança de contexto | Envelhecimento de resultados de ferramentas, resumos estruturados, compressão intraturno, truncamento por orçamento rígido |
| Pré-carregamento de contexto | Ranking de `repo_map` ciente dos requisitos, além de um `context_pack` de fontes relevantes para tarefas complexas (até ~30KB), reduzindo leituras completas repetidas |
| Tarefas de longo horizonte | Orçamentos de etapas, continuação automática, pontos de verificação, registro idempotente de efeitos colaterais (gravações não são reaplicadas) |
| Humano no circuito | Gravações/comandos de alto risco exibem uma prévia de diff e só são executados após aprovação |

Camadas de intenção da sessão: saudações, conversas casuais e perguntas e respostas gerais são respondidas diretamente, sem varrer o workspace, acionar ferramentas ou gravar; apenas tarefas explícitas, como codificação, alterações em arquivos e execução de comandos, entram no ciclo de codificação.

### 1.2 Paralelismo assíncrono multissessão

- Uma sessão = um `asyncio.Task` em segundo plano; alternar janelas, fechar abas ou desconectar não interrompe a tarefa.
- Controle global de concorrência + fila FIFO; ao aguardar aprovação humana, o slot de concorrência é liberado automaticamente.
- Máquina de estados da sessão: `idle → queued → running ⇄ waiting_input → done / error`.
- Barra de abas de sessão na parte superior do workbench: criar ou abrir uma sessão adiciona uma aba automaticamente; clique para alternar horizontalmente; `×` apenas fecha a visualização sem excluir a sessão, e as abas persistem após a atualização; clique com o botão direito em uma aba para fechar a conversa atual / as da esquerda / as da direita / todas.
- A primeira mensagem de uma nova sessão recebe um título curto do modelo no idioma atual da UI; se uma sessão antiga ainda tiver o título padrão, um resumo é exibido automaticamente com base na primeira mensagem.
- Cada sessão tem sua própria URL `/#/s/<session-id>`, que pode ser copiada, atualizada, compartilhada ou acessada diretamente pela barra de endereços.
- Após atualizar a página, mensagens, eventos, planos, aprovações e artefatos são restaurados a partir do SQLite.
- O principal canal de eventos em tempo real usa SSE (reconexão, retomada baseada em cursor, streaming mesmo sem WebSocket); o endpoint WebSocket permanece por compatibilidade; REST oferece suporte à reprodução de eventos.

### 1.3 Supervisor de IA e orquestração multiagente

- **Supervisor**: verificações de integridade entre sessões, alertas de tarefas travadas, interrupção automática, conversas no console e ações de agendamento.
- **Orquestrador**: objetivo → DAG de tarefas → um git worktree independente por funcionário → execução paralela → merge e aceitação.
- As sessões dos funcionários compartilham arquivos de contrato e um blackboard compartilhado; uma falha não bloqueia outras tarefas na mesma camada.

### 1.4 Biblioteca de skills

- Markdown + front-matter declarando `name / title / description / kinds / triggers`.
- Correspondência automática por tipo de tarefa e palavras-chave; a classificação BM25 entra em ação quando há muitas skills.
- Integradas: metodologia central, ciclo de engenharia de repositório, ciclo de depuração, entrega web e redação de propostas.
- Skills podem ser criadas, editadas e excluídas na UI; as alterações entram em vigor ao salvar.

### 1.5 Documentos de plano

- `make_plan`: gera uma proposta/plano HTML independente com KPIs, seções, tabelas, riscos e marcos.
- Os artefatos são registrados em `api/data/artifacts/` e podem ser pré-visualizados/baixados diretamente pelo lado direito do workbench.

### 1.6 Arquitetura de plugins

O HaoYuan não é "um único monólito gigante"; ele é:

```
Kernel (sessions / events / tool registry / policy / model gateway / approvals)
        │
        ├── coding       coding agent + engineering tools + skills
        ├── plans        planning tools + Planner agent
        ├── supervisor   health checks + console routes
        ├── orchestrator task DAG + worktree + merge
        └── embodied     embodied agent harness (disabled by default, install to enable)
```

Plugins podem contribuir com: ferramentas, agentes, rotas HTTP, diretórios de skills, assinaturas de eventos, hooks de ciclo de vida e metadados de navegação/comando do frontend. A falha de carregamento de um único plugin não derruba o kernel.

![Plugins](../screenshots/plugins.png)

### 1.7 Onze idiomas, tema claro padrão e uma barra lateral recolhível

- Tema **claro (branco)** padrão; alterne para o escuro na página de configurações ou na parte inferior da barra lateral.
- Idioma **chinês simplificado** padrão; alterne entre **简体中文 / 繁體中文 / English / 日本語 / Deutsch / 한국어 / Français / Español / Português (Brasil) / Italiano / Polski**.
- Os pontos de entrada de idioma estão em três locais de destaque: a barra superior do workbench, a parte inferior da barra lateral (disponível em todas as páginas) e Configurações → Aparência.
- A escolha é persistida em `localStorage` e sobrevive à atualização e à reinicialização; `document.lang` e o título da página também são atualizados.
- A barra lateral pode ser recolhida para uma faixa de ícones de 76px; após o recolhimento, um botão explícito "Expandir barra lateral" permanece no topo, a lista de sessões fica oculta e tudo é restaurado ao expandir.
- O painel de insights à direita fica recolhido por padrão para deixar mais espaço para a conversa; clique no botão no canto superior direito para abri-lo, e a escolha persiste.
- Títulos/descrições de habilidades integradas, títulos/descrições de plugins e textos da interface para status, botões, dicas, aprovações, planos, uso e orquestração são totalmente cobertos nos onze idiomas.

---

## 2. Início rápido

### Estatísticas de uso anônimas (aviso de transparência)

O HaoYuan inclui um **heartbeat de uso totalmente anônimo** para contar dispositivos online e a distribuição de versões:

- **Dados reportados**: um `install_id` (UUID) aleatório gerado localmente, a versão do cliente e o tipo de SO (ex.: `Windows 11`). Não contém nomes de usuário, e-mails, conteúdos de arquivos, caminhos de workspace, conteúdo de conversas nem quaisquer outros dados pessoais.
- **Frequência**: uma vez na inicialização e a cada 5 minutos durante a execução (uma única solicitação POST leve).
- **Totalmente opcional**: defina a variável de ambiente `HAOYUAN_TELEMETRY=0` antes da inicialização para desativá-lo permanentemente; todos os recursos permanecem inalterados.
- **Proteção de privacidade**: o servidor registra apenas um hash unidirecional do IP, nunca o IP em texto simples; os dados são mantidos por 90 dias.
- **Aviso completo**: consulte o endpoint de privacidade do centro de plugins `GET {plugin-center-url}/api/plugin-center/privacy`, ou o código-fonte `api/core/telemetry.py` (~100 linhas, auditável).

### Requisitos

- Python 3.10+
- Node.js 18+
- Windows / Linux / macOS

### npm install (recomendado)

```bash
# Prerequisite: Node.js 18+ and Python 3.10+
npm install -g haoyuan

# Faster mirrors in mainland China:
npm install -g haoyuan --registry=https://registry.npmmirror.com

# Terminal chat (creates the venv and installs dependencies on first run)
haoyuan

# Start the service and open the web UI automatically
haoyuan web
```

| Comando | Finalidade |
|---|---|
| `haoyuan` | Chat no terminal (saída em streaming, chamadas de ferramentas, prompts de aprovação) |
| `haoyuan --model x/y` | Iniciar chat com um modelo específico (ex.: `--model deepseek/deepseek-flash`) |
| `haoyuan web` | Iniciar o serviço e abrir a interface web automaticamente |
| `haoyuan web --no-open` | Iniciar o serviço sem abrir um navegador |
| `haoyuan --version` / `-V` | Mostrar a versão |
| `haoyuan config` | Arquivo de configuração global (chaves de modelo etc.); use `--open` para editá-lo diretamente |
| `haoyuan login` / `haoyuan logout` | Fazer login quando a proteção de conta estiver habilitada / limpar o token local |
| `haoyuan setup` | Instalar apenas as dependências |
| `haoyuan help` | Mostrar ajuda |

Comandos no terminal: `/models` para visualizar/selecionar um modelo (escolha pelo número, ou `/model x/y` para selecionar diretamente), `/new` para criar uma sessão, `/web` para abrir a sessão atual em um navegador, `/cancel` para cancelar a tarefa atual, `/exit` para sair (Ctrl+C também funciona).

A interface web usa `http://127.0.0.1:8030` por padrão e incrementa a porta automaticamente quando ela está em uso. Sem uma chave de modelo, o modelo integrado `mock` ainda executa sessões, chamadas de ferramentas, aprovações e o frontend de ponta a ponta.

### Inicialização com um clique no Windows

```bat
start.bat
```

O script automaticamente: interrompe o processo antigo na porta 8030 → cria `api/env1` → instala as dependências do Python → (somente quando `web/dist` estiver ausente) instala as dependências do frontend e compila → inicia a API e abre a página do produto. O pacote npm já inclui um frontend pré-compilado, portanto ambientes de intranet/offline podem iniciar diretamente assim que as dependências estiverem instaladas. Se um `npm install` anterior deixou um `web/node_modules` incompleto devido a uma interrupção de rede, o script detecta e reinstala automaticamente — não é necessário excluir manualmente.

**Fallback automático de porta**: o backend usa `8030` por padrão e o servidor de desenvolvimento do frontend usa `8130`; se uma porta estiver em uso, ele incrementa automaticamente (8031, 8032, …) até que o bind seja bem-sucedido. As portas reais são gravadas em `api/data/runtime.json`, e o script de inicialização as lê para abrir o endereço correto. Você também pode definir as portas base explicitamente com `HAOYUAN_PORT` / `HAOYUAN_WEB_PORT` (frontend) e `HAOYUAN_API_PORT` (destino do proxy do frontend).

Parar:

```bat
stop.bat
```

### Console de desktop (desktop.exe)

Dê um clique duplo em `desktop.exe` na raiz do repositório para abrir o console gráfico (~20 KB, dependendo apenas do .NET Framework 4.x incluído no Windows):

- **Iniciar tudo / parar tudo**: gerencia o backend e o servidor de desenvolvimento do frontend com um clique; a página do produto abre automaticamente após a inicialização
- **Iniciar / parar backend** (padrão 8030) e **iniciar / parar frontend** (padrão 8130)
- **Configurações de porta**: edite as portas do backend/frontend diretamente; clique em "Apply ports and restart" para salvar a configuração e reiniciar os dois serviços; se uma porta estiver ocupada, o serviço ainda incrementa a porta automaticamente
- **Abrir página do produto**: abre a porta real do backend a partir de `api/data/runtime.json`; usa a porta do frontend como fallback quando apenas o frontend está em execução
- **Compilar frontend**, **abrir pasta do projeto**, status dos serviços a cada segundo e logs de execução ao vivo

Fechar a janela do console não interrompe os serviços. Para interrompê-los, clique em "Stop all" ou nos botões de parada correspondentes. O código-fonte está em `desktop/`; execute `desktop\build.bat` para recompilar após alterações.

### Linux / macOS

```bash
bash start.sh
bash stop.sh
```

Para ambientes de intranet ou com mirror personalizado, especifique as fontes de download explicitamente (quando omitidas, são usadas as fontes já configuradas em `~/.npmrc` e `pip.conf`):

```bash
export HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
export HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
bash start.sh
```

Equivalente no Windows:

```bat
set HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
set HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
start.bat
```

Quando as dependências do frontend ou do Python estiverem incompletas (por exemplo, uma instalação anterior foi interrompida por `ECONNRESET`), `start.sh` / `start.bat` / `haoyuan setup` detectam e limpam `web/node_modules` automaticamente, reinstalam, instalam os pacotes de backend ausentes e recorrem ao `web/dist` existente se o build falhar.

`web/package-lock.json` não fixa mais um mirror externo; `replace-registry-host=always` em `web/.npmrc` garante que as instalações sempre usem o registro da configuração atual do npm, de modo que o lockfile não possa desviar as instalações para um mirror externo inacessível.

### Inicialização manual

```bash
# Backend
cd api
python -m venv env1
env1\Scripts\activate           # Linux: source env1/bin/activate
pip install -r requirements.txt
python main.py                  # http://127.0.0.1:8030, increments automatically if in use

# Frontend dev mode (hot reload, optional)
cd web
npm install
npm run dev                     # http://localhost:8130, increments automatically if in use; /api and /ws proxy to the backend's actual port
```

Em produção, o backend serve `web/dist` diretamente, então você só precisa acessar a porta real do backend. As portas podem ser substituídas por variáveis de ambiente: `HAOYUAN_PORT` (backend, padrão 8030), `HAOYUAN_WEB_PORT` (frontend, padrão 8130) e `HAOYUAN_API_PORT` (destino do proxy do frontend, padrão de `api/data/runtime.json`).

### Configurar modelos

**Arquivo de configuração global (recomendado)** — um caminho fixo por usuário, não afetado por reinstalação ou atualização:

```bash
haoyuan config          # creates the file on first run and prints its path
haoyuan config --open   # open it directly in your editor
```

Caminho: `~/.config/haoyuan/config.json` (no Windows: `C:\Users\<you>\.config\haoyuan\config.json`; substitua com a variável de ambiente `HAOYUAN_CONFIG`):

O arquivo é criado automaticamente na primeira inicialização (ou pelo postinstall do npm), e seu diretório é criado caso não exista.

```json
{
  "PROVIDER": "",
  "MODEL": "",
  "DEEPSEEK_API_KEY": "",
  "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
  "DEEPSEEK_MODEL": "deepseek-flash",
  "ZHIPU_API_KEY": "",
  "ZHIPU_BASE_URL": "https://open.bigmodel.cn/api/coding/paas/v4",
  "ZHIPU_MODEL": "glm-5.3-flash",
  "MIMO_API_KEY": "",
  "MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
  "MIMO_MODEL": "mimo-v2.6-flash",
  "providers": {}
}
```

- Para provedores integrados, você pode adicionar `DEEPSEEK_MODELS` / `ZHIPU_MODELS` / `MIMO_MODELS` (separados por vírgula) para personalizar totalmente a lista de modelos; `*_THINKING_MODELS`, `*_MAX_OUTPUT` e `*_SUPPORTS_THINKING` são opcionais.
- Qualquer provedor compatível com OpenAI pode ser adicionado ao objeto `providers`, não apenas aos três integrados:

```json
{
  "providers": {
    "my-intranet": {
      "base_url": "http://llm.intranet/v1",
      "api_key": "sk-...",
      "models": ["qwen-max", "qwen-plus"],
      "default_model": "qwen-max",
      "supports_thinking": false,
      "max_output_tokens": 8192
    }
  }
}
```

- `PROVIDER` / `MODEL` podem fixar o modelo padrão (por exemplo, `"MODEL": "deepseek-v4-pro"` ou `"MODEL": "my-intranet/qwen-max"`; deixe vazio para selecionar automaticamente com base nas chaves configuradas).
- **Sincronização bidirecional entre a página de configurações web e o arquivo de configuração**: adicionar/editar provedores, modelos e o modelo padrão em "Configurações → Configuração de modelo" grava de volta no arquivo imediatamente; se você editar o arquivo diretamente e salvar, o serviço o recarrega na próxima requisição (não é necessário reiniciar).
- "Atualizar todos os modelos" consulta o endpoint `/models` de cada provedor com sua URL base e chave, filtrando automaticamente modelos que não são de chat; se alguns provedores falharem, os provedores exatos e os motivos são exibidos, enquanto os provedores bem-sucedidos ainda são salvos.

**Configuração dentro do pacote (opcional)**:

```bash
copy api\configs\secrets_example.py api\configs\secrets_local.py
```

Edite `api/configs/secrets_local.py` com os mesmos campos (como constantes Python). Isso é destinado a implantações a partir do código-fonte; para uma instalação global via npm, o arquivo fica dentro do diretório do pacote e é removido na atualização, então prefira a configuração global.

**Variáveis de ambiente** (maior prioridade):

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

Prioridade: variáveis de ambiente > arquivo de configuração global > `secrets_local.py`. Após editar o arquivo de configuração global, não é necessário reiniciar (o serviço recarrega a quente); o campo `key_source` da verificação de integridade `GET /api/health` mostra de onde a chave veio.

**Quando nenhuma chave está configurada, o modelo local `mock` é usado automaticamente**, exercitando sessões, chamadas de ferramentas, aprovações, eventos e o frontend de ponta a ponta.

---

## 3. Interface

| Workbench (claro, padrão) | Workbench (inglês) |
|---|---|
| ![](../screenshots/workbench-light.png) | ![](../screenshots/workbench-en.png) |

| Workbench (chinês tradicional) | Workbench (escuro) |
|---|---|
| ![](../screenshots/workbench-tw.png) | ![](../screenshots/workbench-dark.png) |

| Console do supervisor | Biblioteca de habilidades |
|---|---|
| ![](../screenshots/console.png) | ![](../screenshots/skills.png) |

| Configurações e entrada de idioma | Botão de expandir após recolher a barra lateral |
|---|---|
| ![](../screenshots/settings.png) | ![](../screenshots/collapsed.png) |

Painel de insights à direita no celular:  
![](../screenshots/mobile-panel.png)

Interações principais:

- Abas de sessão no topo: clique para alternar entre conversas; `×` fecha uma aba (os dados da sessão não são afetados); clique com o botão direito para fechar a conversa atual / à esquerda / à direita / todas
- Novas tarefas não oferecem mais perguntas predefinidas; basta descrever a tarefa na caixa de entrada e o título da sessão é resumido automaticamente
- Roteamento pela barra de endereços: `/#/s/<session-id>` mapeia para uma sessão específica e pode ser copiado, atualizado ou aberto em uma nova janela
- `Ctrl / Cmd + K`: paleta de comandos (navegação, sessões, ações)
- `Ctrl / Cmd + N`: nova tarefa
- `Ctrl / Cmd + B`: recolher / expandir a barra lateral
- `Enter`: enviar; `Shift + Enter`: nova linha (`Ctrl / Cmd + Enter` também envia)
- Cartão de aprovação: `A` aprova, `R` rejeita
- Alternância de idioma: canto superior direito do workbench, parte inferior da barra lateral em qualquer página e Configurações → Aparência
- Digite enquanto uma sessão está em execução: a entrada é mesclada à execução atual como uma "instrução adicional" sem interromper a tarefa
- O painel direito fica recolhido por padrão; clique no botão no canto superior direito para abrir Visão geral / Plano / Arquivos / Alterações / Artefatos e arraste para redimensionar
- Arquivos e diffs usam uma sobreposição de visualização grande para evitar ler código em uma coluna estreita

---

## 4. Arquitetura

```text
hao-yuan/
├── api/
│   ├── main.py                    FastAPI entry (extension routes + plugin routes + static frontend)
│   ├── configs/                   Configuration, model registry, secrets
│   ├── core/
│   │   ├── contracts.py           Tool / Agent / Policy / ToolContext
│   │   ├── storage.py             SQLite (WAL) storage layer
│   │   ├── events.py              Event bus (broadcast + batched persistence + replay)
│   │   ├── gateway.py             Model gateway (streaming + degradation + fallback)
│   │   ├── context.py             Context compression / aging / hard budget
│   │   ├── runtime.py             Agent main loop
│   │   ├── session_manager.py     Concurrency gate / queue / approvals / resume
│   │   ├── policy.py              Permission gate
│   │   ├── tools.py               Tool registry and execution
│   │   ├── agents.py              Agent registry
│   │   └── plugin.py              Plugin discovery / dependencies / lifecycle
│   ├── harness/                   Sandbox / skills / symbol index / fix loop / supervision / orchestration / embodied
│   ├── tools/                     builtin / dev / plan
│   ├── adapters/providers/        deepseek / mimo / mock
│   ├── plugins/                   coding / plans / supervisor / orchestrator / embodied
│   ├── extensions/                System / sessions / skills / settings / files / usage / plugins / approvals / real-time events (SSE / WebSocket)
│   ├── skills/                    Core skills
│   ├── tests/                     90 backend tests
│   └── data/                      Runtime data (gitignored)
├── web/                           Vue 3 + Vite
├── docs/screenshots/              UI screenshots
├── start.bat / stop.bat
├── start.sh / stop.sh
├── dev.bat
├── desktop.exe                    Graphical desktop console (start/stop services / open the web UI)
└── desktop/                       desktop.exe source and build scripts
```

### Dados e limites

- Banco de dados: `api/data/haoyuan.db` (WAL)
- Artefatos: `api/data/artifacts/<session_id>/`
- Portas de runtime: `api/data/runtime.json` (o backend grava `api_port`, o frontend grava `web_port` e o console desktop grava `api_port_config` / `web_port_config`)
- Todas as ferramentas de arquivo são restritas pela allowlist do workspace da sessão e rejeitam `../` e escapes de caminho absoluto.
- Ferramentas de alto risco (gravação de arquivos, patch, exclusão, movimentação, shell, git, movimento de robô) exigem aprovação.
- `run_shell` bloqueia duramente comandos catastróficos (como `rm -rf /`, formatação de disco e desligamento).
- O HTML de artefato é visualizado por meio de um endpoint com CSP de sandbox, impedindo que páginas geradas pelo modelo leiam credenciais locais.
- Segredos são lidos apenas de variáveis de ambiente ou `secrets_local.py`; nunca são armazenados no banco de dados nem retornados em texto simples.
- Chaves reais ficam em `api/configs/secrets_local.py`, que é ignorado por `.gitignore`; `git add --dry-run` verifica se elas nunca entram no repositório.

---

## 5. Desenvolvimento de Plugins

Crie um diretório em `api/plugins/`:

```
api/plugins/my-plugin/
├── plugin.json
├── plugin.py
├── routes.py        # optional
└── skills/          # optional
    └── my-skill.md
```

`plugin.json`:

```json
{
  "name": "my-plugin",
  "title": "My Plugin",
  "version": "1.0.0",
  "description": "What this plugin adds",
  "author": "you",
  "requires": ["coding"],
  "default_enabled": true,
  "backend": "plugin.py",
  "routes": "routes.py",
  "contributes": {
    "tools": ["my_tool"],
    "agents": ["my_agent"],
    "skills": true
  },
  "frontend": {
    "nav": [{ "label": "My Plugin", "path": "/my-plugin", "icon": "puzzle" }],
    "commands": [{ "id": "my-plugin.run", "title": "Run my plugin" }]
  }
}
```

`plugin.py`:

```python
from core.contracts import AgentSpec, ToolSpec


async def my_tool(ctx, args):
    return {"echo": args.get("text", "")}


def register(ctx):
    ctx.register_tool(
        ToolSpec(
            name="my_tool",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        my_tool,
    )
    ctx.register_agent(
        AgentSpec(
            name="my_agent",
            title="My Agent",
            instructions="You are ...",
            tools=["my_tool"],
            kind="dev",
        )
    )
    ctx.add_skill_dir("skills")


async def startup(ctx):
    ...


async def shutdown(ctx):
    ...
```

Capacidades de plugin:

- `requires` controla a ordenação de dependências; dependências ausentes são isoladas e o erro é registrado.
- Hooks de ciclo de vida `startup / shutdown`.
- `ctx.events.subscribe(sink)` se inscreve em eventos globais (é assim que o orquestrador recebe eventos de conclusão de funcionários).
- O estado habilitado/desabilitado é persistido no SQLite; após alternar, reinicie a API para carregar/descarregar as rotas.
- O frontend obtém os metadados `contributes` e `frontend` via `/api/plugins`.

### Por que este design

Ele toma emprestado do WordPress o modelo de "kernel pequeno + plugins instaláveis": o kernel cuida apenas de sessões, eventos, políticas, modelos e do protocolo de ferramentas; todas as capacidades de negócio ficam nos plugins.  
Ele também adota a ideia do DeepSeek Harness de que "o próprio harness é plugável": um agente corporificado é apenas um plugin de harness independente, então você pode continuar adicionando harnesses para rovers, braços robóticos, robôs humanoides e muito mais sem tocar no kernel.

---

## 6. Resultados do Autoteste

O seguinte foi executado no ambiente de entrega:

```bash
cd api
python -m pytest -q
# 90 passed, 2 skipped, 2 warnings

cd ../web
npm run build
# ✓ built, 97 modules transformed
```

Cobertura dos testes:

- Verificação de integridade, modelos, skills, plugins e listagem de aprovações
- Uma sessão completa com modelo mock (mensagem → evento → concluído)
- Sessão de codificação: gravação de arquivo → evento de ferramenta → artefato → leitura da árvore do workspace
- Fluxo de aprovação humana: pendente → aprovar → execução da ferramenta → arquivo gravado em disco
- Renomear / ocultar / restaurar / limpar / excluir permanentemente a sessão
- Configurações de gate global e do workspace padrão, uso e exportação CSV
- Persistência do estado de habilitação dos plugins
- Orquestrador git worktree de ponta a ponta (criar → despachar → concluir → mesclar)
- Nível de ferramenta: escape de sandbox, read/write/edit/patch/multi_edit, glob/grep/symbols, shell, delete/move
- Bloqueio rígido de comandos shell perigosos
- Índice de símbolos, mapa do repositório, parsing de pytest e orientação para correções
- Geração de artefato HTML de plano
- Roteamento de intenções: saudações, conversa fiada e perguntas e respostas gerais (como "como vai você", "que tempo bom hoje", "o que é injeção de dependência") são respondidas diretamente sem varrer o workspace, acionar ferramentas ou gravar (incluindo verificação real com deepseek-flash)
- Título automático da sessão a partir da primeira mensagem (segue o idioma da UI; o mock cobre fallback e verificação com modelo real)
- Roteamento independente de sessões: deep links `/#/s/<session-id>`, troca de abas, edição da barra de endereços, restauração após atualização e fallback ao fechar
- Clique com o botão direito na aba da sessão: fechar atual / à esquerda / à direita / todas, com troca automática para a aba mais próxima após o fechamento em massa
- Atualização de modelos do provedor: detalhes de falha e filtragem de modelos que não são de chat

Além disso, foi feita uma inspeção da build de produção em navegador real com Playwright + Chrome local:

- As páginas de painel de trabalho / console / habilidades / plugins / configurações / uso / orquestração carregam
- Abas de sessão no topo e roteamento independente: abrir, alternar, fechar, fechamento em massa com clique direito, links diretos da barra de endereço e restauração após atualização
- Sumarização do título padrão, menu de idioma no canto superior direito (alternância entre onze idiomas) e estado vazio sem perguntas predefinidas
- A alternância entre chinês simplificado, chinês tradicional, inglês, japonês, alemão, coreano, francês, espanhol, português do Brasil, italiano e polonês funciona, e o idioma persiste após a atualização
- Os pontos de entrada de idioma abrangem a barra superior do painel de trabalho, a parte inferior da barra lateral e a página de configurações
- O recolhimento/expansão da barra lateral entre 286px e 76px funciona; após recolher, a lista de sessões fica oculta e o botão de expansão fica visível
- O painel de insights à direita fica recolhido por padrão, e seu estado expandido/recolhido persiste
- `Enter` envia e `Shift + Enter` insere uma nova linha; a composição do IME não envia acidentalmente
- Os temas escuro / claro funcionam
- O layout móvel de 430px, a gaveta da barra lateral e a gaveta de insights à direita funcionam
- Fluxo em tempo real via SSE: raciocínio e deltas de conteúdo reais do DeepSeek ficam visíveis antes de `done`
- Sem erros de JS, sem recursos 404 e sem WebSocket 404 no console (o principal canal em tempo real agora é SSE)

> A verificação online real foi concluída com a chave DeepSeek referenciada pelo assistente de IA: `deepseek-flash` retornou `OK`, e o uso de provider/model = `deepseek/deepseek-flash`. A chave é armazenada apenas em `api/configs/secrets_local.py`, que é ignorado por `.gitignore`; o repositório faz commit apenas do template `secrets_example.py`. Os testes de regressão com mock permanecem, então o sistema degrada automaticamente quando está offline ou sem uma chave.

---

## 7. Resultados do benchmark justo do Harness

> Relatório mais recente: `test/testing/index-2026-10-27.html` (2026-10-27, mimo-v2.6-flash)  
> Relatório histórico: `test/testing/index-2026-10-25.html` (2026-10-25, deepseek-flash)

### 7.1 Benchmark justo do MiMo (mais recente)

**Método**: 5 tarefas avaliáveis automaticamente (1 adaptativa básica + 4 cobrindo localização / desempenho / horizonte longo / concorrência) × 3 ferramentas; `mimo-v2.6-flash`, prompts, repositório semente e orçamento unificados. Testes ocultos são injetados após a execução, e `tests/` e `pyproject.toml` são verificados por SHA-256 — adulteração pontua 0. t1/d1/d3 usam o lote intercalado official-r1; d4/d6 usam um lote de reexecução independente após o congelamento do código.

| Classificação | Ferramenta | Geral (ponderado pelo produto) | Correção | Velocidade | Custo | Disciplina de engenharia | Ponderação igual |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **98,8** | 100,0 | 94,4 | 96,9 | 100,0 | **98,3 (1º)** |
| 2 | OpenCode | 90,5 | 100,0 | 67,8 | 53,5 | 100,0 | 84,3 (2º) |
| 3 | Claude Code | 88,9 | 100,0 | 65,1 | 40,9 | 100,0 | 81,2 (3º) |

Geral = 0,65 × correção + 0,15 × velocidade + 0,10 × custo + 0,10 × disciplina de engenharia; a fórmula de ponderação igual usa 0,40 / 0,20 / 0,20 / 0,20.

- As três ferramentas obtiveram 100% de correção; HaoYuan obteve **98.8** na ponderação por produto e **98.3** com pesos iguais, ficando em primeiro lugar em ambas as fórmulas.
- Por tarefa: HaoYuan foi o mais rápido em t1 (63.8s), d3 (220.6s) e d4 (469.6s); OpenCode venceu em d1 (111.3s), e Claude Code venceu em d6 (254.5s).
- Custo: o custo total para as 5 tarefas foi de **$3.33** para HaoYuan, $6.56 para OpenCode e $9.04 para Claude Code; os custos por tarefa foram $0.666 / $1.313 / $1.809.
- Intensidade adaptativa: t1, uma tarefa fácil, levou 63.8s e 11 chamadas sem iniciar um plano ou subagente; a tarefa de horizonte longo d4 usou código-fonte relevante pré-carregado para reduzir a exploração repetida (de um tempo limite de 1200s para 469.6s).
- Principais correções: conclusão do provedor MiMo (anteriormente, `resolve("mimo", ...)` recorria silenciosamente ao deepseek como fallback), mapa de repositório ciente dos requisitos, um pacote de contexto de 30KB para tarefas complexas, recuperação da árvore de processos, provedor estrito + limites por chamada + novas tentativas no mesmo modelo, e roteamento lite para tarefas fáceis.
- Limitações: a comparação formal usou 1 rodada por tarefa; d4/d6 foram lotes de reexecução independentes; a variância de latência do modelo é grande (Claude d3 foi 623s antes e 884s desta vez); d5 não teve poder discriminatório e não entrou no ranking; as tarefas foram construídas internamente e não podem substituir benchmarks públicos como o SWE-bench.

Reproduza:

```bash
cd test/bench
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks t1_multisite_bugfix,d1_needle_regress,d3_perf_cliff --resume
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks d4_multilayer_feature,d6_concurrency_fix --resume
python make_report_mimo_final.py
```

### 7.2 Benchmark profundo do deepseek-flash (histórico)

**Método**: 8 tarefas de programação corrigíveis automaticamente (5 básicas + 3 difíceis) × 3 rodadas por tarefa × 3 ferramentas; deepseek-flash, prompts, repositório inicial e orçamento unificados; os testes ocultos são injetados após a execução, e `tests/` e `pyproject.toml` são verificados por SHA-256 — adulteração resulta em pontuação 0.

| Classificação | Ferramenta | Pontuação geral (ponderada por produto) | Correção | Velocidade típica | Latência de cauda | Custo | Pontuação com pesos iguais |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **96.6** | 100.0 | 100.0 (mediana 30.3s) | 67.6 (P90 159.4s) | 82.2 ($0.364) | 95.0 (2º) |
| 2 | OpenCode | 95.1 | 100.0 | 67.6 (mediana 44.8s) | 100.0 (P90 107.7s) | 100.0 ($0.299) | 96.8 (1º) |
| 3 | Claude Code | 90.7 | 100.0 | 70.6 (mediana 42.9s) | 90.7 (P90 118.7s) | 55.4 ($0.540) | 91.7 (3º) |

Geral = 0.70 × correção + 0.15 × velocidade típica + 0.05 × latência de cauda + 0.10 × custo; a fórmula com pesos iguais altera os dois últimos pesos para 0.10 / 0.10.

- Os três obtiveram 100% de acerto; as diferenças concentraram-se em velocidade, latência de cauda e custo de tokens; HaoYuan ficou em primeiro na ponderação por produto, enquanto OpenCode o superou em peso igual.
- HaoYuan teve o menor tempo mediano de tarefa, 30,3 s, e foi o mais rápido na mediana de quatro tarefas (T1/T2/T3/H1); todas as 24 execuções foram 100% concluídas. OpenCode teve a melhor latência de cauda e o melhor custo por tarefa; Claude Code teve o maior custo de tokens.
- Pontos fracos: a migração de versão H2 teve mediana de 159,4 s (OpenCode: 101,1 s), e H3 teve uma cauda longa de 260 s; trabalhos futuros comprimirão ainda mais as auditorias de migração e as rodadas de autoteste.
- Limitações: cobre apenas deepseek-flash e 3 rodadas por tarefa; as tarefas são construídas internamente e não substituem benchmarks públicos como o SWE-bench.
- Autoiteração: durante a avaliação, foram corrigidos a adaptação de pipe no Windows, a proteção contra resposta vazia/ausência de escrita, as auditorias de aceitação de migração, as auditorias leves de git diff e a ordenação de conclusão; uma otimização negativa de "excesso de testes" foi revertida.

Reproduzir:

```bash
cd test/bench
python harness_bench.py run --batch final-r1 --tools haoyuan,claude,opencode --tasks all
python aggregate.py
python make_report.py
```

---

## 8. Paridade de recursos com o Assistente de IA

| Recurso | HaoYuan | Observações |
|---|---|---|
| Cadeia de ferramentas de codificação | ✅ | Localização, patches mínimos, verificação, ciclo de correção, subagentes |
| Compressão de contexto / horizonte longo | ✅ | Compressão no turno, envelhecimento, orçamento rígido, checkpoints, retomada idempotente |
| Paralelismo multissessão | ✅ | Portão de concorrência, FIFO, tarefas em segundo plano desacopladas do frontend |
| Portão de permissões / aprovação de diff | ✅ | Cartões de aprovação, pré-visualização, timeout, liberação de slot de concorrência |
| Biblioteca de habilidades | ✅ | front-matter + regras/BM25 + edição na UI |
| Documentos de plano | ✅ | Artefatos HTML autônomos |
| Supervisor de IA | ✅ | Snapshots, alertas, conversas no console, ações de agendamento |
| Orquestração multiagente | ✅ | DAG de tarefas + git worktree + métricas de merge |
| Estatísticas de tokens / custo | ✅ | Agregação diária, por modelo, exportação CSV |
| Mecanismo de plugins | ✅ Aprimorado | Manifesto, dependências, ciclo de vida, metadados de tools/agents/routes/skills/frontend |
| Comando remoto do Feishu | ⏳ Não nesta versão | A camada de interface é desacoplada e pode ser adicionada como plugin |
| ASR / TTS / renderização de vídeo | ⏳ Não nesta versão | O foco atual é o ciclo central de codificação por IA |
| Benchmarks autoritativos | ⏳ Benchmarks públicos não executados | Os benchmarks internos estão completos: um benchmark justo MiMo de 5 tarefas e um benchmark profundo deepseek de 8 tarefas (ver Seção 7); benchmarks públicos como SWE-bench não foram reexecutados |

---

## 9. Roteiro (arquitetura já reservada)

### 9.1 Biblioteca de habilidades para treinamento local em 16 GB de VRAM

Itens integrados planejados:

- Scripts de construção de dados e treinamento SFT para Qwen3.5-0.8B
- Scripts de treinamento RL (otimização de preferência / recompensas verificáveis)
- Configurações amigáveis à memória: LoRA / QLoRA, acumulação de gradientes, lotes pequenos, controle de comprimento de sequência
- Organizados por "habilidade": modelos de dados, configurações de treinamento, casos de avaliação e notas de implantação

O mecanismo atual de Skills do HaoYuan já é baseado em arquivos e versionável, então documentos de metodologia de treinamento podem ser posteriormente injetados nos agentes como Skills.

### 9.2 Harness incorporado baseado em plugins

`plugins/embodied` já demonstra:

- Ferramentas de estado do robô / sensores / movimento / direção / parada de emergência
- Aprovação de ações de alto risco
- Uma ponte de demonstração HTTP

Sem alterar o kernel, você pode adicionar posteriormente:

- `embodied-ros2` (tópicos / serviços ROS2)
- `embodied-serial` (Arduino / ESP32)
- `embodied-smolvla` (modelo de visão-linguagem-ação)
- Plugins de harness para rovers, braços robóticos e robôs humanoides

---

## 10. Visão geral da API

Prefixo unificado `/api`, formato de resposta `{ code, data, message }`.

| Grupo | Principais endpoints |
|---|---|
| Sistema | `GET /health`, `GET /info`, `GET /models`, `GET /agents`, `GET /tools` |
| Sessões | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `PATCH /sessions/{id}` |
| Mensagens | `POST /sessions/{id}/messages`, `GET /sessions/{id}/messages` |
| Eventos | `GET /sessions/{id}/events?after_id=`, `GET /sessions/{id}/stream`, `WS /ws` |
| Aprovações | `GET /approvals`, `POST /approvals/{id}/resolve`, `POST /sessions/{id}/confirm` |
| Habilidades | `GET/POST /skills`, `GET/PUT/DELETE /skills/{name}` |
| Arquivos | `GET /workspace/tree`, `GET /workspace/file`, `GET /workspace/changes`, `GET /workspace/diff` |
| Configurações | `GET/PUT /settings`, `PUT /settings/gate`, `PUT /settings/workspace` |
| Uso | `GET /usage/today`, `GET /usage/daily`, `GET /usage/by-model`, `GET /usage/export.csv` |
| Plugins | `GET /plugins`, `POST /plugins/{name}/toggle` |
| Supervisor | `GET /supervisor/overview`, `GET /supervisor/console`, `POST /supervisor/act`, `POST /supervisor/chat` |
| Orquestração | `POST /orchestrations`, `GET /orchestrations`, `GET /orchestrations/{id}` |

Documentação interativa: <http://127.0.0.1:8030/docs> (após um incremento de porta, use o log do backend ou `api/data/runtime.json`).

---

## 11. Desenvolvimento e Testes

```bash
cd api
python -m pytest -q

cd ../web
npm run build
npm run dev        # dev mode; /api and /ws proxy to the backend's actual port automatically
```

Recomendamos registrar os comandos de lint / teste / build da sua equipe em `AGENTS.md`; o HaoYuan injeta automaticamente a memória do projeto no contexto.

---

## Licença

Este projeto é distribuído sob a MIT License e é livre para usar, modificar e distribuir.
