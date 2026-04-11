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

import concurrent.futures # <--- Adicione no topo do arquivo
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
    """Faz busca no Bing Images e retorna lista de URLs de imagens."""
    query = quote_plus(f"{produto} {TERMO_EXTRA}")
    url = f"https://www.bing.com/images/search?q={query}"

    headers = random.choice(HEADERS_LIST)
    headers["Referer"] = "https://www.bing.com/"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Erro ao buscar '{produto}': {e}")
        return []

    # O Bing guarda os links originais em alta resolução dentro de um atributo chamado 'murl'
    padrao = re.compile(r'murl&quot;:&quot;(https?://[^&]+?\.(?:jpg|jpeg|png|webp))&quot;', re.IGNORECASE)
    urls = padrao.findall(resp.text)

    urls_filtradas = [
        u for u in urls
        if "bing.net" not in u and len(u) < 500
    ]

    return list(dict.fromkeys(urls_filtradas))[:max_urls]


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

def processar_produto(produto_info, pasta, session):
    """Função que será executada em paralelo para cada produto"""
    nome_busca, nome_arquivo = produto_info
    
    nome_final = sanitizar_nome(nome_arquivo)
    nome_final = re.sub(r'\.(jpg|jpeg|png|webp)$', '', nome_final, flags=re.IGNORECASE)
    nome_final += ".png"
    caminho_img = pasta / nome_final

    if caminho_img.exists():
        return "EXISTE"

    # Busca as URLs (passando a session para ser mais rápido)
    urls = buscar_urls_imagens(nome_busca) 
    
    for url in urls:
        # Tenta baixar a imagem
        img = baixar_imagem(url) # Dica: você pode passar a session aqui também
        if img is None: continue

        try:
            img_sem_fundo = remover_fundo(img)
            img_sem_fundo.save(caminho_img, "PNG")
            # Pequeno delay para não ser banido pelo buscador
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            return "SUCESSO"
        except Exception:
            continue
            
    return "FALHA"

def main():
    pasta = Path(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(CSV_FILE):
        log.error(f"Arquivo '{CSV_FILE}' não encontrado!")
        return

    produtos = ler_produtos_csv(CSV_FILE)
    log.info(f"🚀 Iniciando processamento paralelo para {len(produtos)} produtos.")

    sucesso = 0
    falha = 0
    ja_existia = 0

    # Usamos ThreadPoolExecutor para rodar em paralelo
    # max_workers=5 é um valor seguro. Se sua CPU for forte, tente 10.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Usamos uma sessão global para o Requests
        with requests.Session() as session:
            # Mapeia a função para a lista de produtos
            futures = {executor.submit(processar_produto, p, pasta, session): p for p in produtos}
            
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(produtos), desc="Progresso"):
                resultado = future.result()
                if resultado == "SUCESSO": sucesso += 1
                elif resultado == "EXISTE": ja_existia += 1
                else: falha += 1

    log.info(f"Concluído! Sucesso: {sucesso} | Falhas: {falha} | Já existiam: {ja_existia}")

if __name__ == "__main__":
    main()