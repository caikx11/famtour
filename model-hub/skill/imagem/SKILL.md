---
name: imagem
description: Gera imagens localmente na GPU do usuario (ComfyUI via Model Hub), sem gastar tokens. Use quando o usuario digitar /imagem ou pedir para criar, gerar ou desenhar uma imagem, icone, ilustracao ou foto.
---

# /imagem - gerar imagens localmente

    python "%MODEL_HUB%\hubctl.py" imagem "<descricao>" [--saida caminho.png] [--tamanho LxA]

- Escreva a descricao **em ingles**, detalhada (assunto, estilo, luz, enquadramento).
- `--saida`: salve dentro do projeto quando a imagem for para ele (ex: `assets/logo.png`).
- `--tamanho`: `1024x1024` (padrao), `1344x768` (paisagem) ou `768x1344` (retrato).
- Demora de 10 s a 2 min (a primeira vez liga o ComfyUI). Use timeout longo no comando.
- O modelo de texto local sai da GPU durante a geracao e volta sozinho depois.

Ao terminar, diga onde a imagem foi salva. Se der erro, mostre a mensagem; se o hub estiver
fora do ar, peca ao usuario para rodar `claude-hub` ou `iniciar.bat`.
