# Model Hub

Um endereço só (`http://localhost:4000`) para usar o **Claude** e os **seus modelos locais** (Ollama / `.gguf`).

- Detecta sozinho modelos novos do Ollama e arquivos `.gguf` da pasta configurada.
- Painel com seletor: **Auto** (Claude e, quando os tokens acabam, o modelo local), **Só Claude** e **Só local**.
- Funciona com o Claude Code (API Anthropic) e com Aider e bots (API OpenAI em `/v1/chat/completions`).

## Instalação (Windows)
1. Instale o [Python 3.11+](https://python.org) (marque "Add to PATH") e o [Ollama](https://ollama.com) (versão recente, com suporte à API Anthropic).
2. Baixe um modelo, por exemplo `ollama pull qwen3-coder:30b` ou `ollama pull gpt-oss:20b`.
3. Em `model-hub/config.json`, coloque em `pasta_gguf` a pasta onde ficam os seus `.gguf` (ou deixe vazio).
4. Rode `model-hub\instalar.bat` uma vez. Para ver o painel, use `model-hub\iniciar.bat` ou abra http://localhost:4000.
5. Em qualquer terminal novo, digite `claude-hub`. Ele liga o Ollama e o hub sozinho e abre o Claude Code.

Para o Aider ou um bot, use a base URL `http://localhost:4000/v1` com qualquer API key.

## Modelos sugeridos para RTX 5070 Ti (16 GB) e 64 GB de RAM
| Modelo | Uso |
|---|---|
| `qwen3-coder:30b` | O melhor para programar. Parte fica na RAM, mas ainda é rápido (MoE). |
| `gpt-oss:20b` | Cabe inteiro na GPU e é bom com ferramentas. |
| `qwen3:14b` | Rápido, bom para os agentes do Discord. |
