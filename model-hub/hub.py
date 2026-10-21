"""
Model Hub - um endereco so para o Claude e para os seus modelos locais.

- Detecta sozinho os modelos do Ollama e os arquivos .gguf da pasta configurada.
- Pagina web (http://localhost:4000) com seletor de modelo.
- Fala a API da Anthropic (/v1/messages) -> Claude Code funciona apontando para ca.
- Fala a API da OpenAI (/v1/chat/completions) -> Aider, bots do Discord etc.
- Modo "auto": usa o Claude e, se acabar credito / bater limite, repete no modelo local.
"""
import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "estado.json"

DEFAULT_CONFIG = {
    "porta": 4000,
    "ollama_url": "http://localhost:11434",
    "anthropic_url": "https://api.anthropic.com",
    "pasta_gguf": [],
    "intervalo_scan_segundos": 10,
    "modo": "auto",
    "modelo_local": "",
}

# Respostas do Claude que indicam "sem tokens" -> cai para o modelo local
FALLBACK_STATUS = {402, 429, 529}
FALLBACK_TEXTOS = ("credit", "rate_limit", "usage limit", "quota", "overloaded")

log = logging.getLogger("hub")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def ler_json(path, padrao):
    try:
        return {**padrao, **json.loads(path.read_text(encoding="utf-8"))}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(padrao)


def salvar_json(path, dados):
    path.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


config = ler_json(CONFIG_FILE, DEFAULT_CONFIG)
estado = ler_json(STATE_FILE, {"gguf_importados": {}, "modo": config["modo"], "modelo_local": config["modelo_local"]})
modelos_locais: list[dict] = []
ultimo_uso = {"modelo": None, "quando": None}

app = FastAPI(title="Model Hub")
client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))


# ---------------------------------------------------------------- deteccao

def nome_para_gguf(arquivo: Path) -> str:
    nome = arquivo.stem.lower().replace(" ", "-").replace("_", "-")
    return "gguf-" + "".join(c for c in nome if c.isalnum() or c in "-.")


def importar_gguf(arquivo: Path) -> bool:
    """Registra um .gguf no Ollama (ollama create) para ele virar um modelo normal."""
    nome = nome_para_gguf(arquivo)
    modelfile = BASE / f".Modelfile-{nome}"
    modelfile.write_text(f'FROM "{arquivo}"\n', encoding="utf-8")
    log.info("Importando %s como '%s'...", arquivo.name, nome)
    try:
        r = subprocess.run(["ollama", "create", nome, "-f", str(modelfile)], capture_output=True, text=True)
    except FileNotFoundError:
        log.error("Comando 'ollama' nao encontrado. Instale o Ollama.")
        return False
    finally:
        modelfile.unlink(missing_ok=True)
    if r.returncode != 0:
        log.error("Falha ao importar %s: %s", arquivo.name, r.stderr.strip())
        return False
    estado["gguf_importados"][str(arquivo)] = nome
    salvar_json(STATE_FILE, estado)
    return True


def escanear_gguf():
    pastas = config.get("pasta_gguf") or []
    if isinstance(pastas, str):
        pastas = [pastas]
    arquivos = [a for p in pastas if Path(p).is_dir() for a in Path(p).rglob("*.gguf")]
    for arq in arquivos:
        # pula pedacos de modelos divididos (so importa a parte 1) e projetores de visao
        if "mmproj" in arq.name.lower() or ("-of-" in arq.name and "-00001-of-" not in arq.name):
            continue
        if str(arq) not in estado["gguf_importados"]:
            importar_gguf(arq)


async def atualizar_modelos():
    global modelos_locais
    await asyncio.to_thread(escanear_gguf)
    try:
        r = await client.get(f"{config['ollama_url']}/api/tags")
        r.raise_for_status()
        novos = [
            {"nome": m["name"], "tamanho_gb": round(m.get("size", 0) / 1e9, 1),
             "detalhes": m.get("details", {}).get("parameter_size", "")}
            for m in r.json().get("models", [])
        ]
    except Exception as e:
        log.warning("Ollama indisponivel (%s)", e.__class__.__name__)
        return
    antigos = {m["nome"] for m in modelos_locais}
    for m in novos:
        if m["nome"] not in antigos:
            log.info("Modelo disponivel: %s", m["nome"])
    modelos_locais = novos


async def loop_scan():
    while True:
        await atualizar_modelos()
        await asyncio.sleep(config["intervalo_scan_segundos"])


@app.on_event("startup")
async def iniciar():
    asyncio.create_task(loop_scan())


def modelo_local_ativo() -> str | None:
    nomes = [m["nome"] for m in modelos_locais]
    if estado.get("modelo_local") in nomes:
        return estado["modelo_local"]
    return nomes[0] if nomes else None


# ---------------------------------------------------------------- roteamento

def headers_para(destino: str, request: Request) -> dict:
    ignorar = {"host", "content-length", "accept-encoding", "connection"}
    h = {k: v for k, v in request.headers.items() if k.lower() not in ignorar}
    if destino == "local":
        h = {k: v for k, v in h.items() if k.lower() not in ("authorization", "x-api-key")}
    return h


def deve_cair_para_local(status: int, corpo: bytes) -> bool:
    if status in FALLBACK_STATUS:
        return True
    if status in (400, 403):
        texto = corpo.decode("utf-8", "ignore").lower()
        return any(t in texto for t in FALLBACK_TEXTOS)
    return False


async def encaminhar(url: str, headers: dict, corpo: dict):
    """Envia e devolve (status, headers, gerador_do_corpo, corpo_lido_se_erro)."""
    req = client.build_request("POST", url, headers=headers, json=corpo)
    resp = await client.send(req, stream=True)
    if resp.status_code >= 400:
        dados = await resp.aread()
        await resp.aclose()
        return resp, dados
    return resp, None


def responder(resp: httpx.Response, dados: bytes | None):
    tipo = resp.headers.get("content-type", "application/json")
    if dados is not None:
        return Response(dados, status_code=resp.status_code, media_type=tipo)

    async def gerar():
        try:
            async for pedaco in resp.aiter_raw():
                yield pedaco
        finally:
            await resp.aclose()

    return StreamingResponse(gerar(), status_code=resp.status_code, media_type=tipo)


def registrar(modelo):
    ultimo_uso.update(modelo=modelo, quando=time.strftime("%H:%M:%S"))


async def chamar_local(caminho: str, request: Request, corpo: dict):
    modelo = modelo_local_ativo()
    if not modelo:
        return JSONResponse({"type": "error", "error": {"type": "api_error",
                             "message": "Nenhum modelo local disponivel. Abra o Ollama e baixe um modelo."}},
                            status_code=503)
    corpo = {**corpo, "model": modelo}
    registrar(modelo)
    resp, dados = await encaminhar(f"{config['ollama_url']}{caminho}", headers_para("local", request), corpo)
    return responder(resp, dados)


@app.post("/v1/messages")
async def messages(request: Request):
    corpo = await request.json()
    modo = estado.get("modo", "auto")
    if modo == "local":
        return await chamar_local("/v1/messages", request, corpo)

    resp, dados = await encaminhar(f"{config['anthropic_url']}/v1/messages", headers_para("claude", request), corpo)
    if modo == "auto" and dados is not None and deve_cair_para_local(resp.status_code, dados):
        log.info("Claude respondeu %s -> usando modelo local", resp.status_code)
        return await chamar_local("/v1/messages", request, corpo)
    registrar(corpo.get("model"))
    return responder(resp, dados)


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    corpo = await request.json()
    if estado.get("modo") != "local":
        resp, dados = await encaminhar(f"{config['anthropic_url']}/v1/messages/count_tokens",
                                       headers_para("claude", request), corpo)
        if dados is None or resp.status_code < 400:
            return responder(resp, dados)
    # estimativa simples (~4 caracteres por token) para o modelo local
    return {"input_tokens": len(json.dumps(corpo)) // 4}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """API estilo OpenAI (Aider, bots, etc.) -> sempre o modelo local selecionado."""
    return await chamar_local("/v1/chat/completions", request, await request.json())


@app.get("/v1/models")
async def listar_openai():
    return {"object": "list", "data": [{"id": m["nome"], "object": "model"} for m in modelos_locais]}


# ---------------------------------------------------------------- painel

@app.get("/api/estado")
async def api_estado():
    return {"modo": estado.get("modo"), "modelo_local": modelo_local_ativo(),
            "modelos": modelos_locais, "ultimo_uso": ultimo_uso}


@app.post("/api/selecionar")
async def api_selecionar(request: Request):
    dados = await request.json()
    if dados.get("modo") in ("auto", "claude", "local"):
        estado["modo"] = dados["modo"]
    if "modelo_local" in dados:
        estado["modelo_local"] = dados["modelo_local"]
    salvar_json(STATE_FILE, estado)
    log.info("Modo: %s | modelo local: %s", estado["modo"], modelo_local_ativo())
    return await api_estado()


@app.post("/api/escanear")
async def api_escanear():
    await atualizar_modelos()
    return await api_estado()


@app.get("/", response_class=HTMLResponse)
async def painel():
    return (BASE / "painel.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config["porta"], log_level="warning")
