"""
=============================================================
  Script: Buscador de Imagens de Produtos para Mercado
=============================================================
  Como usar:
  1. Instale as dependências:
       pip install requests pillow tqdm rembg

  2. Coloque o arquivo CSV com os produtos na mesma pasta
     que este script. O CSV deve ter duas colunas:
       - nome_produto : usado para buscar a imagem no Google
       - nome_imagem  : usado para nomear o arquivo salvo

  3. Execute:
       python teste.py

  4. Para rodar o script no WSL2
        Primeiro crie o ambiente dentro do linux
            python3 -m venv venv
            source venv/bin/activate
        Depois rode os comandos de instalação dos pacotes normalmente
            pip install requests pillow tqdm rembg
            pip install "rembg[cpu]"

  ATENÇÃO: As imagens serão salvas em PNG (com fundo transparente).
           O formato JPG não suporta transparência.
=============================================================
"""

import os
import re
import csv
import time
import random
import logging
import requests
from pathlib import Path
from urllib.parse import quote_plus
from PIL import Image
from io import BytesIO
from tqdm import tqdm
from rembg import remove
from ddgs import DDGS

# ─────────────────────────────────────────────
#  ⚙️  CONFIGURAÇÕES — AJUSTE AQUI
# ─────────────────────────────────────────────
CSV_FILE        = "produtos.csv"       # Caminho para o seu arquivo CSV
COLUNA_BUSCA    = "nome_produto"       # Coluna usada para buscar a imagem no Google
COLUNA_ARQUIVO  = "nome_imagem"        # Coluna usada para nomear o arquivo salvo
PASTA_SAIDA     = "imagens_produtos"   # Pasta onde as imagens serão salvas
DELAY_MIN       = 1.5                  # Espera mínima entre buscas (segundos)
DELAY_MAX       = 3.5                  # Espera máxima entre buscas (segundos)
TAMANHO_MIN_KB  = 5                    # Ignora imagens menores que X KB
TERMO_EXTRA     = "produto mercado"    # Termo extra para refinar a busca
LOG_FILE        = "log_download.txt"   # Arquivo de log
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.0 Safari/605.1.15",
        "Accept-Language": "pt-BR,pt;q=0.9",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) "
                      "Gecko/20100101 Firefox/121.0",
        "Accept-Language": "pt-BR,pt;q=0.9",
    },
]


def sanitizar_nome(nome: str) -> str:
    """Remove caracteres inválidos para nome de arquivo."""
    caracteres_invalidos = r'\/:*?"<>|'
    for c in caracteres_invalidos:
        nome = nome.replace(c, "_")
    return nome.strip()[:100]



def buscar_urls_imagens(produto: str, max_urls: int = 5) -> list:
    """
    Busca imagens no DuckDuckGo.
    Possui retry automático em caso de rate limit.
    """

    busca = f"{produto} {TERMO_EXTRA}"

    for tentativa in range(3):
        try:
            with DDGS(timeout=20) as ddgs:
                resultados = ddgs.images(
                    busca,
                    region="br-pt",
                    safesearch="off",
                    max_results=max_urls
                )

                urls = []

                for r in resultados:
                    url = r.get("image")

                    if not url:
                        continue

                    if len(url) > 500:
                        continue

                    urls.append(url)

                urls = list(dict.fromkeys(urls))

                if urls:
                    return urls

        except Exception as e:
            log.warning(
                f"Tentativa {tentativa + 1}/3 falhou para "
                f"'{produto}': {e}"
            )

            # espera progressiva
            time.sleep(random.uniform(5, 12))

    return []


def baixar_imagem(url: str) -> Image.Image | None:
    """Baixa uma imagem e retorna o objeto PIL, ou None em caso de falha."""
    headers = random.choice(HEADERS_LIST)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        conteudo = resp.content

        if len(conteudo) < TAMANHO_MIN_KB * 1024:
            return None

        return Image.open(BytesIO(conteudo)).convert("RGBA")

    except Exception:
        return None


def remover_fundo(img: Image.Image) -> Image.Image:
    """Remove o fundo da imagem usando rembg e retorna imagem com transparência."""
    buffer_entrada = BytesIO()
    img.save(buffer_entrada, format="PNG")
    buffer_entrada.seek(0)

    resultado = remove(buffer_entrada.read())
    return Image.open(BytesIO(resultado)).convert("RGBA")


def ler_produtos_csv(caminho: str) -> list:
    """Lê o CSV e retorna lista de tuplas (nome_para_buscar, nome_para_salvar)."""
    produtos = []
    with open(caminho, newline="", encoding="latin1") as f:
        reader = csv.DictReader(f, delimiter=";")

        for linha in reader:
            nome_busca   = linha.get(COLUNA_BUSCA, "").strip()
            nome_arquivo = linha.get(COLUNA_ARQUIVO, "").strip()

            if not nome_busca:
                continue

            if not nome_arquivo:
                nome_arquivo = nome_busca

            produtos.append((nome_busca, nome_arquivo))

    return produtos


def main():
    pasta = Path(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(CSV_FILE):
        log.error(f"Arquivo '{CSV_FILE}' não encontrado!")
        return

    produtos = ler_produtos_csv(CSV_FILE)
    log.info(f"✅ {len(produtos)} produtos encontrados no CSV.")
    log.info(f"ℹ️  As imagens serão salvas em PNG com fundo transparente.")

    sucesso    = 0
    falha      = 0
    ja_existia = 0

    for nome_busca, nome_arquivo in tqdm(produtos, desc="Baixando imagens", unit="produto"):
        # Salva sempre como .png (transparência exige PNG)
        nome_final = sanitizar_nome(nome_arquivo)
        nome_final = re.sub(r'\.(jpg|jpeg|png|webp)$', '', nome_final, flags=re.IGNORECASE)
        nome_final += ".png"

        caminho_img = pasta / nome_final

        # Pula se já foi baixada
        if caminho_img.exists():
            ja_existia += 1
            continue

        urls = buscar_urls_imagens(nome_busca)

        baixou = False
        for url in urls:
            img = baixar_imagem(url)
            if img is None:
                continue

            try:
                log.info(f"🔄 Removendo fundo: '{nome_busca}'...")
                img_sem_fundo = remover_fundo(img)
                img_sem_fundo.save(caminho_img, "PNG")
                log.info(f"✔ '{nome_busca}' → {nome_final}")
                sucesso += 1
                baixou = True
                break
            except Exception as e:
                log.warning(f"Erro ao remover fundo de '{nome_busca}': {e}")
                continue

        if not baixou:
            log.warning(f"✘ Sem imagem para: '{nome_busca}' (arquivo esperado: {nome_final})")
            falha += 1

        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    log.info("=" * 50)
    log.info(f"🎉 CONCLUÍDO!")
    log.info(f"   ✔ Baixados com sucesso : {sucesso}")
    log.info(f"   ⏭ Já existiam         : {ja_existia}")
    log.info(f"   ✘ Falhas               : {falha}")
    log.info(f"   📁 Imagens salvas em   : {pasta.resolve()}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()