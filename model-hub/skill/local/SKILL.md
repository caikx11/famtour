---
name: local
description: Gerencia o Model Hub (modelos locais na GPU do usuario via Ollama) e delega tarefas simples ao modelo local para economizar tokens. Use quando o usuario digitar /local, pedir para trocar de modelo/modo, ver modelos locais, ou economizar tokens.
---

# /local - Model Hub

O hub roda em http://localhost:4000. Controle tudo com:

    python "%MODEL_HUB%\hubctl.py" <comando>

(`MODEL_HUB` e a pasta do model-hub, definida pelo instalar.bat.)

| Comando | O que faz |
|---|---|
| `status` | modo atual, modelo ativo, lista de modelos |
| `modo auto` / `modo claude` / `modo local` | troca o modo de roteamento |
| `modelo NOME` | escolhe o modelo local |
| `perguntar "tarefa" [--arquivo X ...]` | executa a tarefa no modelo local e imprime a resposta |

## Argumentos de /local
- sem argumento -> rode `status` e mostre o resultado.
- `auto`, `claude`, `local` -> rode `modo <arg>`.
- nome de modelo -> rode `modelo <nome>`.
- qualquer outro texto -> trate como tarefa e delegue com `perguntar`.

## Economizar tokens (delegacao)
Delegue ao modelo local tarefas **simples e autocontidas**, que ele faz bem:
- resumir arquivos grandes ou logs longos (passe com `--arquivo` em vez de ler voce mesmo);
- gerar codigo repetitivo/boilerplate, docstrings, comentarios, mensagens de commit;
- traduzir, reescrever textos, gerar dados de teste.

Mantenha com voce: decisoes de arquitetura, depuracao dificil, mudancas em varios arquivos, seguranca.

Sempre **revise** a resposta do modelo local antes de usar - ele erra mais. Se a resposta for ruim, faca voce mesmo e avise o usuario.
Se o hub estiver fora do ar, diga ao usuario para rodar `claude-hub` ou `iniciar.bat`.
