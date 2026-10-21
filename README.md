# Model Hub

Um endereço só (`http://localhost:4000`) para usar o **Claude** e os **seus modelos locais** (Ollama / `.gguf`).

- Detecta sozinho modelos novos do Ollama e arquivos `.gguf` da pasta configurada.
- Painel com seletor: **Auto** (Claude e, quando os tokens acabam, o modelo local), **Só Claude** e **Só local**.
- Funciona com o Claude Code (API Anthropic) e com Aider e bots (API OpenAI em `/v1/chat/completions`).

## Instalação (Windows)
1. Instale o [Python 3.11+](https://python.org) (marque "Add to PATH") e o [Ollama](https://ollama.com) (versão recente, com suporte à API Anthropic).
2. Baixe um modelo, por exemplo `ollama pull qwen3-coder:30b` ou `ollama pull gpt-oss:20b`.
3. Em `model-hub/config.json`, coloque em `pasta_gguf` as pastas onde ficam os seus `.gguf`, por exemplo `["C:\\Modelos", "D:\\IA"]`. Pode ser uma pasta ou várias. Se não tiver nenhuma, use `[]`.
4. Rode `model-hub\instalar.bat` uma vez. Para ver o painel, use `model-hub\iniciar.bat` ou abra http://localhost:4000.
5. Em qualquer terminal novo, digite `claude-hub`. Ele liga o Ollama e o hub sozinho e abre o Claude Code.

Para o Aider ou um bot, use a base URL `http://localhost:4000/v1` com qualquer API key.

## Modelos sugeridos para RTX 5070 Ti (16 GB) e 64 GB de RAM
| Modelo | Uso |
|---|---|
| `qwen3-coder:30b` | O melhor para programar. Parte fica na RAM, mas ainda é rápido (MoE). |
| `gpt-oss:20b` | Cabe inteiro na GPU e é bom com ferramentas. |
| `qwen3:14b` | Rápido, bom para os agentes do Discord. |

## Skill `/local` (Claude Code)
O `instalar.bat` instala a skill em `%USERPROFILE%\.claude\skills\local`. Dentro do Claude Code:
- `/local`: mostra o modo e os modelos.
- `/local auto`, `/local claude` ou `/local local`: troca o modo.
- `/local qwen3:14b`: escolhe o modelo local.
- `/local resuma o arquivo X`: o Claude passa a tarefa para o modelo local e economiza tokens.

O Claude também usa a skill sozinho para tarefas simples, como resumos, boilerplate e mensagens de commit.

## Otimizações automáticas
O `instalar.bat` configura o Ollama para a RTX 5070 Ti de 16 GB com 64 GB de RAM:
- **Flash attention**: deixa o modelo mais rápido e gasta menos memória.
- **Cache KV em 8 bits** (`q8_0`): cabe quase o dobro de contexto na GPU, com perda mínima de qualidade.
- **Contexto de 32k**: o Claude Code precisa de bastante contexto.
- **1 modelo e 1 pedido por vez**: a VRAM fica toda para o modelo ativo.
- **Modelo fica carregado por 30 minutos**: assim ele não recarrega a cada pedido.

Para ver se o modelo está todo na GPU, rode `ollama ps`. A coluna PROCESSOR deve mostrar `100% GPU`. Se aparecer, por exemplo, `30%/70% CPU/GPU`, parte do modelo está na RAM e ele fica mais lento. É normal no `qwen3-coder:30b`.
