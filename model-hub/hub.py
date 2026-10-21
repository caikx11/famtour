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
import threading
import time
from contextlib import asynccontextmanager
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
    "ignorar": ["image", "vae", "diffusion", "embed", "bge-", "whisper", "tts"],
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
pastas_avisadas: set[str] = set()
trava_scan = threading.Lock()
falhas: set[str] = set()
cache_recursos: dict[str, list[str]] = {}
ultimo_uso = {"modelo": None, "quando": None}

app = FastAPI(title="Model Hub")
client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))


# ---------------------------------------------------------------- deteccao

def nome_para_gguf(arquivo: Path) -> str:
    nome = arquivo.stem.lower().replace(" ", "-").replace("_", "-")
    return "gguf-" + "".join(c for c in nome if c.isalnum() or c in "-.")


def achar_mmproj(arquivo: Path) -> Path | None:
    """Arquivo de visao (mmproj) que fica na mesma pasta do modelo, se existir. Prefere F16."""
    candidatos = sorted(arquivo.parent.glob("*mmproj*.gguf"))
    for c in candidatos:
        if "f16" in c.name.lower() and "bf16" not in c.name.lower():
            return c
    return candidatos[0] if candidatos else None


def ollama_create(nome: str, linhas: list[str]):
    modelfile = BASE / f".Modelfile-{nome}"
    modelfile.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    try:
        return subprocess.run(["ollama", "create", nome, "-f", str(modelfile)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    finally:
        modelfile.unlink(missing_ok=True)


def importar_gguf(arquivo: Path) -> bool:
    """Registra um .gguf no Ollama (ollama create) para ele virar um modelo normal.
    Se houver um mmproj na pasta, tenta importar junto (visao); se falhar, importa so o texto."""
    nome = nome_para_gguf(arquivo)
    mmproj = achar_mmproj(arquivo)
    log.info("Importando %s como '%s'%s...", arquivo.name, nome, " (com visao)" if mmproj else "")
    try:
        r = None
        if mmproj:
            r = ollama_create(nome, [f'FROM "{arquivo}"', f'FROM "{mmproj}"'])
            if r.returncode == 0:
                estado.setdefault("com_visao", []).append(nome)
            else:
                log.warning("Visao nao suportada para %s, importando so o texto", nome)
        if r is None or r.returncode != 0:
            r = ollama_create(nome, [f'FROM "{arquivo}"'])
    except FileNotFoundError:
        log.error("Comando 'ollama' nao encontrado. Instale o Ollama.")
        return False
    if r.returncode != 0:
        # guarda a falha para nao ficar tentando o mesmo arquivo a cada scan
        falhas.add(str(arquivo))
        erro = (r.stderr or "").strip().splitlines()
        log.error("Falha ao importar %s: %s", arquivo.name, erro[-1] if erro else r.returncode)
        return False
    estado["gguf_importados"][str(arquivo)] = nome
    if mmproj:
        estado.setdefault("visao_tentada", []).append(nome)
    salvar_json(STATE_FILE, estado)
    cache_recursos.pop(nome + ":latest", None)
    log.info("Importado: %s", nome)
    return True


def escanear_gguf():
    # roda numa thread propria; se uma importacao demorada ainda esta em andamento, nao comeca outra
    if not trava_scan.acquire(blocking=False):
        return
    try:
        _escanear_gguf()
    finally:
        trava_scan.release()


def _escanear_gguf():
    pastas = config.get("pasta_gguf") or []
    if isinstance(pastas, str):
        pastas = [pastas]
    arquivos = []
    for p in pastas:
        if not Path(p).is_dir():
            if p not in pastas_avisadas:
                log.warning("Pasta de modelos nao encontrada: %s (confira o config.json)", p)
                pastas_avisadas.add(p)
            continue
        achados = list(Path(p).rglob("*.gguf"))
        if p not in pastas_avisadas:
            log.info("%s: %d arquivo(s) .gguf encontrado(s)", p, len(achados))
            pastas_avisadas.add(p)
        arquivos += achados
    for arq in arquivos:
        # pula pedacos de modelos divididos (so importa a parte 1) e projetores de visao
        caminho = str(arq).lower()
        if "mmproj" in arq.name.lower() or ("-of-" in arq.name and "-00001-of-" not in arq.name):
            continue
        # modelos que nao sao de texto (imagem, embeddings, audio) ou que o usuario nao quer
        if any(p.lower() in caminho for p in config.get("ignorar", [])):
            continue
        # o mesmo arquivo pode existir em mais de uma pasta: importa so uma vez por nome
        if str(arq) in falhas:
            continue
        nome = nome_para_gguf(arq)
        if str(arq) not in estado["gguf_importados"] and nome not in estado["gguf_importados"].values():
            importar_gguf(arq)
        elif (str(arq) in estado["gguf_importados"] and nome not in estado.get("visao_tentada", [])
              and achar_mmproj(arq)):
            # importado antes sem visao: refaz com o mmproj (rapido, o Ollama reaproveita o arquivo ja copiado)
            importar_gguf(arq)


async def recursos_do_modelo(nome: str) -> list[str]:
    """O que o modelo sabe fazer segundo o Ollama: 'tools' (ferramentas), 'vision' (imagens)..."""
    if nome not in cache_recursos:
        try:
            r = await client.post(f"{config['ollama_url']}/api/show", json={"model": nome})
            cache_recursos[nome] = r.json().get("capabilities", [])
        except Exception:
            return []
    return cache_recursos[nome]


def tirar_imagens(corpo: dict) -> dict:
    """Troca imagens por um aviso em texto, para modelos que nao enxergam."""
    aviso = {"type": "text", "text": "[imagem removida: o modelo local atual nao enxerga imagens]"}

    def limpar(conteudo):
        if not isinstance(conteudo, list):
            return conteudo
        saida = []
        for bloco in conteudo:
            if isinstance(bloco, dict) and bloco.get("type") in ("image", "image_url"):
                saida.append(aviso)
            elif isinstance(bloco, dict) and bloco.get("type") == "tool_result":
                saida.append({**bloco, "content": limpar(bloco.get("content"))})
            else:
                saida.append(bloco)
        return saida

    return {**corpo, "messages": [{**m, "content": limpar(m.get("content"))} for m in corpo.get("messages", [])]}


async def atualizar_modelos():
    global modelos_locais
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
    for m in novos:
        m["recursos"] = await recursos_do_modelo(m["nome"])
    antigos = {m["nome"] for m in modelos_locais}
    for m in novos:
        if m["nome"] not in antigos:
            log.info("Modelo disponivel: %s", m["nome"])
    modelos_locais = novos


async def loop_scan():
    while True:
        # importacao em segundo plano: a lista de modelos continua atualizando enquanto copia
        if not trava_scan.locked():
            asyncio.create_task(asyncio.to_thread(escanear_gguf))
        await atualizar_modelos()
        await asyncio.sleep(config["intervalo_scan_segundos"])


@asynccontextmanager
async def ciclo_de_vida(_app):
    tarefa = asyncio.create_task(loop_scan())
    yield
    tarefa.cancel()


app.router.lifespan_context = ciclo_de_vida


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
    if "vision" not in await recursos_do_modelo(modelo):
        corpo = tirar_imagens(corpo)
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

async def modelos_carregados() -> dict:
    """Modelos que estao na memoria agora (ollama ps): nome -> GB na GPU e % na GPU."""
    try:
        r = await client.get(f"{config['ollama_url']}/api/ps")
        saida = {}
        for m in r.json().get("models", []):
            total, vram = m.get("size", 0), m.get("size_vram", 0)
            saida[m["name"]] = {"vram_gb": round(vram / 1e9, 1),
                                "gpu_pct": round(100 * vram / total) if total else 0}
        return saida
    except Exception:
        return {}


@app.get("/api/estado")
async def api_estado():
    carregados = await modelos_carregados()
    modelos = [{**m, "carregado": carregados.get(m["nome"])} for m in modelos_locais]
    return {"modo": estado.get("modo"), "modelo_local": modelo_local_ativo(),
            "modelos": modelos, "ultimo_uso": ultimo_uso,
            "vram_total_gb": round(sum(c["vram_gb"] for c in carregados.values()), 1)}


@app.post("/api/carregar")
async def api_carregar(request: Request):
    nome = (await request.json())["modelo"]
    log.info("Carregando %s na memoria...", nome)
    # pedido vazio so carrega o modelo; keep_alive -1 = fica carregado ate ser liberado
    await client.post(f"{config['ollama_url']}/api/generate", json={"model": nome, "keep_alive": -1})
    return await api_estado()


@app.post("/api/liberar")
async def api_liberar(request: Request):
    nome = (await request.json()).get("modelo")
    nomes = [nome] if nome else list(await modelos_carregados())
    for n in nomes:
        log.info("Liberando %s da memoria", n)
        await client.post(f"{config['ollama_url']}/api/generate", json={"model": n, "keep_alive": 0})
    return await api_estado()


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
