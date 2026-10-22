"""
Geracao de imagens pelo ComfyUI.

- Classifica arquivos de modelo em texto x imagem (cabecalho do GGUF ou nome do arquivo).
- Gera o extra_model_paths.yaml para o ComfyUI enxergar as mesmas pastas do hub.
- Liga o ComfyUI sozinho quando precisa, libera os modelos de texto da GPU antes de gerar
  e devolve a memoria ao terminar.
"""
import asyncio
import json
import logging
import os
import random
import struct
import subprocess
import sys
import time
from pathlib import Path

import httpx

log = logging.getLogger("hub")

BASE = Path(__file__).parent
PASTA_SAIDA = BASE / "imagens"
WORKFLOW_PERSONALIZADO = BASE / "workflow_imagem.json"

# valores de general.architecture de modelos de imagem (GGUFs de difusao do ComfyUI-GGUF)
ARQUITETURAS_IMAGEM = {
    "flux", "sd1", "sdxl", "sd3", "aura", "hidream", "cosmos", "ltxv", "hyvid", "wan",
    "lumina2", "qwen_image", "chroma", "hunyuan", "hunyuan_image", "stable_diffusion",
}
NOMES_IMAGEM = ("qwen-image", "qwen_image", "flux", "sdxl", "sd3", "stable-diffusion", "hidream", "chroma")
# partes de um pipeline de imagem que nao sao "o modelo" em si
NOMES_COMPONENTE = ("vae", "text_encoder", "text-encoder", "clip", "tokenizer", "mmproj", "lora")

DEFAULT = {
    "comfyui_url": "http://127.0.0.1:8188",
    # pasta do ComfyUI portable (a que tem run_nvidia_gpu.bat) ou a pasta ComfyUI com main.py
    "comfyui_pasta": "",
    # pedacos do nome dos arquivos auxiliares do Qwen-Image
    "text_encoder": "qwen_2.5_vl",
    "vae": "qwen_image_vae",
    "passos": 8,
    "cfg": 1.0,
    "shift": 3.1,
    "largura": 1024,
    "altura": 1024,
}


# ---------------------------------------------------------------- classificacao

_cache_arq: dict[str, str | None] = {}


def arquitetura_gguf(arquivo: Path) -> str | None:
    """Le general.architecture do cabecalho de um .gguf sem carregar o modelo."""
    chave = str(arquivo)
    if chave not in _cache_arq:
        _cache_arq[chave] = _ler_arquitetura(arquivo)
    return _cache_arq[chave]


def _ler_arquitetura(arquivo: Path) -> str | None:
    tamanhos = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    try:
        with open(arquivo, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            f.read(4 + 8)  # versao, numero de tensores
            (n_kv,) = struct.unpack("<Q", f.read(8))

            def texto():
                (n,) = struct.unpack("<Q", f.read(8))
                return f.read(n).decode("utf-8", "replace")

            def pular(tipo):
                if tipo == 8:
                    texto()
                elif tipo == 9:
                    (sub,) = struct.unpack("<I", f.read(4))
                    (n,) = struct.unpack("<Q", f.read(8))
                    for _ in range(n):
                        pular(sub)
                else:
                    f.read(tamanhos[tipo])

            for _ in range(min(n_kv, 64)):
                chave = texto()
                (tipo,) = struct.unpack("<I", f.read(4))
                if chave == "general.architecture" and tipo == 8:
                    return texto()
                pular(tipo)
    except (OSError, struct.error, KeyError):
        return None
    return None


def e_componente(arquivo: Path) -> bool:
    caminho = str(arquivo).lower().replace("\\", "/")
    return any(n in arquivo.name.lower() for n in NOMES_COMPONENTE) or any(
        f"/{n}/" in caminho for n in ("vae", "text_encoder", "tokenizer"))


def e_modelo_de_imagem(arquivo: Path) -> bool:
    if arquivo.suffix == ".gguf":
        arq = arquitetura_gguf(arquivo)
        if arq:
            return arq in ARQUITETURAS_IMAGEM
    caminho = str(arquivo).lower()
    return any(n in caminho for n in NOMES_IMAGEM)


def achar_modelos_imagem(pastas: list[str]) -> list[dict]:
    modelos = []
    for p in pastas:
        if not Path(p).is_dir():
            continue
        for arq in Path(p).rglob("*"):
            if arq.suffix not in (".gguf", ".safetensors") or e_componente(arq):
                continue
            if "-of-" in arq.name and "-00001-of-" not in arq.name:
                continue
            if e_modelo_de_imagem(arq):
                modelos.append({"nome": arq.stem, "arquivo": str(arq), "base": p,
                                "tamanho_gb": round(arq.stat().st_size / 1e9, 1)})
    return modelos


def achar_componente(pastas: list[str], pedaco: str) -> tuple[str, str] | None:
    """Acha um arquivo auxiliar (text encoder, VAE) pelo nome; devolve (base, caminho)."""
    pedaco = pedaco.lower()
    for p in pastas:
        if Path(p).is_dir():
            for arq in Path(p).rglob("*"):
                if arq.suffix in (".gguf", ".safetensors") and pedaco in arq.name.lower():
                    return p, str(arq)
    return None


# ---------------------------------------------------------------- ComfyUI

class Gerador:
    def __init__(self, config: dict, client: httpx.AsyncClient, liberar_texto):
        self.cfg = {**DEFAULT, **config.get("imagem", {})}
        self.pastas = config.get("pasta_gguf") or []
        if isinstance(self.pastas, str):
            self.pastas = [self.pastas]
        self.client = client
        self.liberar_texto = liberar_texto
        self.modelos: list[dict] = []
        self.ocupado = asyncio.Lock()
        self.processo = None
        self.usou_gpu = False

    @property
    def url(self):
        return self.cfg["comfyui_url"]

    def pasta_comfy(self) -> Path | None:
        p = self.cfg.get("comfyui_pasta")
        if not p:
            return None
        p = Path(p)
        return p / "ComfyUI" if (p / "ComfyUI" / "main.py").exists() else p

    def atualizar(self):
        self.modelos = achar_modelos_imagem(self.pastas)
        self.escrever_caminhos()

    def escrever_caminhos(self):
        """Faz o ComfyUI procurar modelos nas mesmas pastas do hub (extra_model_paths.yaml)."""
        comfy = self.pasta_comfy()
        if not comfy or not comfy.is_dir():
            return
        arq = comfy / "extra_model_paths.yaml"
        marca = "# gerado pelo model-hub"
        if arq.exists() and marca not in arq.read_text(encoding="utf-8", errors="ignore"):
            log.warning("%s ja existe e nao foi criado pelo hub; adicione as pastas de modelos nele a mao", arq)
            return
        linhas = [marca]
        for i, p in enumerate(self.pastas):
            linhas += [f"model_hub_{i}:", f"  base_path: {Path(p).as_posix()}",
                       "  diffusion_models: .", "  unet: .", "  text_encoders: .", "  clip: .", "  vae: ."]
        novo = "\n".join(linhas) + "\n"
        if not arq.exists() or arq.read_text(encoding="utf-8") != novo:
            arq.write_text(novo, encoding="utf-8")
            log.info("ComfyUI configurado para ler as pastas de modelos (%s)", arq)

    async def online(self) -> bool:
        try:
            return (await self.client.get(f"{self.url}/system_stats", timeout=3)).status_code == 200
        except httpx.HTTPError:
            return False

    async def ligar(self):
        if await self.online():
            return
        comfy = self.pasta_comfy()
        if not comfy or not (comfy / "main.py").exists():
            raise RuntimeError("ComfyUI desligado. Configure 'imagem.comfyui_pasta' no config.json ou abra o ComfyUI.")
        python = comfy.parent / "python_embeded" / "python.exe"
        cmd = [str(python) if python.exists() else sys.executable, "-s", str(comfy / "main.py"),
               "--windows-standalone-build", "--port", self.url.rsplit(":", 1)[-1]]
        log.info("Ligando o ComfyUI...")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        self.processo = subprocess.Popen(cmd, cwd=str(comfy), creationflags=flags)
        for _ in range(120):
            await asyncio.sleep(1)
            if await self.online():
                log.info("ComfyUI pronto")
                return
        raise RuntimeError("O ComfyUI nao respondeu em 2 minutos. Veja a janela dele.")

    def relativo(self, base: str, arquivo: str) -> str:
        # o ComfyUI identifica os arquivos pelo caminho relativo a base_path
        return os.path.relpath(arquivo, base)

    def montar_workflow(self, modelo: dict, prompt: str, negativo: str, largura: int, altura: int, seed: int):
        te = achar_componente(self.pastas, self.cfg["text_encoder"])
        vae = achar_componente(self.pastas, self.cfg["vae"])
        valores = {"{{prompt}}": prompt, "{{negativo}}": negativo, "{{largura}}": largura,
                   "{{altura}}": altura, "{{seed}}": seed, "{{passos}}": self.cfg["passos"],
                   "{{cfg}}": self.cfg["cfg"], "{{modelo}}": self.relativo(modelo["base"], modelo["arquivo"])}

        if WORKFLOW_PERSONALIZADO.exists():
            # workflow exportado do ComfyUI ("Save (API)") com os marcadores {{prompt}}, {{modelo}}...
            def trocar(v):
                if isinstance(v, dict):
                    return {k: trocar(x) for k, x in v.items()}
                if isinstance(v, list):
                    return [trocar(x) for x in v]
                return valores.get(v, v) if isinstance(v, str) else v
            return trocar(json.loads(WORKFLOW_PERSONALIZADO.read_text(encoding="utf-8")))

        faltando = [n for n, c in (("text encoder", te), ("VAE", vae)) if not c]
        if faltando:
            raise RuntimeError(f"Faltam arquivos do Qwen-Image: {', '.join(faltando)}. "
                               f"Procurei por '{self.cfg['text_encoder']}' e '{self.cfg['vae']}' nas pastas de modelos.")
        gguf = modelo["arquivo"].endswith(".gguf")
        te_gguf = te[1].endswith(".gguf")
        return {
            "1": {"class_type": "UnetLoaderGGUF" if gguf else "UNETLoader",
                  "inputs": {"unet_name": valores["{{modelo}}"], **({} if gguf else {"weight_dtype": "default"})}},
            "2": {"class_type": "CLIPLoaderGGUF" if te_gguf else "CLIPLoader",
                  "inputs": {"clip_name": self.relativo(*te), "type": "qwen_image"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.relativo(*vae)}},
            "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": self.cfg["shift"]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negativo}},
            "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": largura, "height": altura, "batch_size": 1}},
            "8": {"class_type": "KSampler", "inputs": {
                "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
                "seed": seed, "steps": self.cfg["passos"], "cfg": self.cfg["cfg"],
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
            "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "model-hub"}},
        }

    async def gerar(self, prompt: str, nome_modelo: str | None = None, negativo: str = "",
                    largura: int | None = None, altura: int | None = None) -> Path:
        if not self.modelos:
            await asyncio.to_thread(self.atualizar)
        modelo = next((m for m in self.modelos if m["nome"] == nome_modelo), None) or \
            (self.modelos[0] if self.modelos else None)
        if not modelo:
            raise RuntimeError("Nenhum modelo de imagem encontrado nas pastas de modelos.")
        async with self.ocupado:
            await self.liberar_texto()  # texto e imagem nao cabem juntos em 16 GB
            await self.ligar()
            wf = self.montar_workflow(modelo, prompt, negativo, largura or self.cfg["largura"],
                                      altura or self.cfg["altura"], random.randint(0, 2**32 - 1))
            log.info("Gerando imagem com %s: %s", modelo["nome"], prompt[:60])
            inicio = time.time()
            r = await self.client.post(f"{self.url}/prompt", json={"prompt": wf})
            if r.status_code != 200:
                raise RuntimeError(f"ComfyUI recusou o pedido: {r.text[:500]}")
            pid = r.json()["prompt_id"]
            self.usou_gpu = True
            while True:
                await asyncio.sleep(1)
                h = (await self.client.get(f"{self.url}/history/{pid}")).json().get(pid)
                if not h:
                    continue
                if h.get("status", {}).get("status_str") == "error":
                    msgs = [m for m in h["status"].get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError(f"Erro no ComfyUI: {msgs[-1][1].get('exception_message') if msgs else h['status']}")
                imgs = [i for out in h.get("outputs", {}).values() for i in out.get("images", [])]
                if imgs:
                    break
            img = imgs[0]
            dados = (await self.client.get(f"{self.url}/view", params=img)).content
            PASTA_SAIDA.mkdir(exist_ok=True)
            destino = PASTA_SAIDA / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
            destino.write_bytes(dados)
            log.info("Imagem pronta em %.0fs: %s", time.time() - inicio, destino.name)
            return destino

    async def liberar(self):
        """Tira os modelos de imagem da GPU (para o modelo de texto voltar a caber)."""
        if self.usou_gpu and await self.online():
            await self.client.post(f"{self.url}/free", json={"unload_models": True, "free_memory": True})
            log.info("Modelo de imagem liberado da GPU")
        self.usou_gpu = False
