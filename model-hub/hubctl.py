"""Controle do Model Hub pela linha de comando (usado pela skill /local).

  python hubctl.py status                 -> modo, modelo ativo e modelos disponiveis
  python hubctl.py modo auto|claude|local -> troca o modo
  python hubctl.py modelo NOME            -> escolhe o modelo local
  python hubctl.py imagem "descricao" [--saida arquivo.png] [--tamanho 1344x768]
                                         -> gera uma imagem pelo ComfyUI
  python hubctl.py perguntar "texto"      -> manda uma tarefa para o modelo local
      (o texto tambem pode vir pela entrada padrao; --arquivo CAMINHO anexa arquivos)
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HUB = "http://localhost:4000"


def chamar(caminho, dados=None, timeout=600):
    req = urllib.request.Request(HUB + caminho, method="POST" if dados is not None else "GET",
                                 data=json.dumps(dados).encode() if dados is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        sys.exit(f"Hub fora do ar ({e}). Rode iniciar.bat ou claude-hub.")


def mostrar(e):
    print(f"Modo: {e['modo']} | modelo local: {e['modelo_local'] or 'nenhum'}")
    for m in e["modelos"]:
        marca = "*" if m["nome"] == e["modelo_local"] else " "
        print(f" {marca} {m['nome']:40} {m['detalhes']:>6} {m['tamanho_gb']} GB")


def perguntar(args):
    arquivos = []
    while "--arquivo" in args:
        i = args.index("--arquivo")
        arquivos.append(args[i + 1])
        del args[i:i + 2]
    texto = " ".join(args) or sys.stdin.read()
    for a in arquivos:
        texto += f"\n\n--- {a} ---\n" + Path(a).read_text(encoding="utf-8", errors="ignore")
    r = chamar("/v1/chat/completions", {"model": "local", "messages": [{"role": "user", "content": texto}]})
    if "choices" not in r:
        sys.exit(json.dumps(r, ensure_ascii=False))
    print(r["choices"][0]["message"]["content"])


def imagem(args):
    saida = tamanho = None
    if "--saida" in args:
        i = args.index("--saida"); saida = args[i + 1]; del args[i:i + 2]
    if "--tamanho" in args:
        i = args.index("--tamanho"); tamanho = args[i + 1]; del args[i:i + 2]
    pedido = {"prompt": " ".join(args)}
    if tamanho:
        pedido["largura"], pedido["altura"] = map(int, tamanho.lower().split("x"))
    r = chamar("/api/imagem", pedido, timeout=900)
    if "erro" in r:
        sys.exit("Erro: " + r["erro"])
    arquivo = Path(r["arquivo"])
    if saida:
        Path(saida).write_bytes(arquivo.read_bytes())
        arquivo = Path(saida)
    print(f"Imagem salva em {arquivo.resolve()}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("status", [])
    if cmd == "status":
        mostrar(chamar("/api/estado"))
    elif cmd == "modo" and args:
        mostrar(chamar("/api/selecionar", {"modo": args[0]}))
    elif cmd == "modelo" and args:
        mostrar(chamar("/api/selecionar", {"modelo_local": args[0]}))
    elif cmd == "imagem" and args:
        imagem(args)
    elif cmd == "perguntar":
        perguntar(args)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
