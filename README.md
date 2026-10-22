# Model Hub

Um endereço só (`http://localhost:4000`) para usar o **Claude** e os **seus modelos locais** (Ollama / `.gguf`).

- Detecta sozinho modelos novos do Ollama e arquivos `.gguf` da pasta configurada.
- Painel com seletor: **Auto** (Claude e, quando os tokens acabam, o modelo local), **Só Claude** e **Só local**.
- Funciona com o Claude Code (API Anthropic) e com Aider e bots (API OpenAI em `/v1/chat/completions`).

## Instalação (Windows)
1. Instale o [Python 3.11+](https://python.org) (marque "Add to PATH") e o [Ollama](https://ollama.com) (versão recente, com suporte à API Anthropic).
2. Baixe um modelo, por exemplo `ollama pull qwen3-coder:30b` ou `ollama pull gpt-oss:20b`.
3. Em `model-hub/config.json`, coloque em `pasta_gguf` as pastas onde ficam os seus `.gguf`, por exemplo `["C:\\Modelos", "D:\\IA"]`. Pode ser uma pasta ou várias. Se não tiver nenhuma, use `[]`.
   Em `ignorar`, coloque partes de nomes de modelos que não devem ser importados. Lembre que cada modelo importado ocupa espaço de novo no disco, porque o Ollama faz uma cópia.
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

## Contexto do modelo local
O Claude Code manda junto com cada pedido as instruções e as ferramentas de todos os plugins e servidores MCP. Isso pode passar de 100 mil tokens, mas o modelo local trabalha com 32 mil. Por isso, no modo local, o hub mantém só as ferramentas listadas em `ferramentas_locais` no `config.json`. Use `/context` no Claude Code para ver o que está ocupando espaço.

## Imagens (ComfyUI)
O hub separa sozinho os modelos de **texto** (vão para o Ollama) dos de **imagem** (vão para o ComfyUI). Ele lê o tipo no cabeçalho do `.gguf` e, nos arquivos `.safetensors`, se guia pelo nome.

**Instalação (uma vez):**
1. Baixe o **ComfyUI Portable para NVIDIA** em https://github.com/comfyanonymous/ComfyUI/releases e extraia, por exemplo em `C:\ComfyUI_windows_portable`.
2. Instale o nó **ComfyUI-GGUF**, necessário para modelos `.gguf`. Na pasta `ComfyUI_windows_portable`, rode:
   ```
   git clone https://github.com/city96/ComfyUI-GGUF ComfyUI\custom_nodes\ComfyUI-GGUF
   python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\ComfyUI-GGUF\requirements.txt
   ```
3. O Qwen-Image também precisa de um **text encoder** e de um **VAE** no formato do ComfyUI. Baixe os dois para uma das pastas de modelos, em https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/tree/main/split_files:
   - `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
   - `vae/qwen_image_vae.safetensors`
4. No `config.json`, em `"imagem"`, coloque em `"comfyui_pasta"` a pasta do ComfyUI.

**Como usar:**
- **No painel:** use a seção "Imagens".
- **No Claude Code:** `/imagem um gato astronauta, estilo aquarela`.
- **No terminal:** `python hubctl.py imagem "a cat astronaut" --saida gato.png`.

O hub liga o ComfyUI sozinho, tira o modelo de texto da placa antes de gerar e devolve a placa no próximo pedido de texto. As imagens ficam em `model-hub\imagens`.

**Outros modelos de imagem (Flux, SDXL...):** monte o workflow no ComfyUI, exporte com **Save (API)** e salve como `model-hub\workflow_imagem.json`. Nos campos que variam, escreva `{{prompt}}`, `{{negativo}}`, `{{modelo}}`, `{{largura}}`, `{{altura}}`, `{{seed}}`, `{{passos}}` e `{{cfg}}`. O hub troca esses marcadores a cada pedido.
