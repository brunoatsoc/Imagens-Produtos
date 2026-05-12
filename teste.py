"""
=============================================================
  Script: Buscador de Imagens de Produtos para Mercado
=============================================================
  Como usar:
  1. Instale as dependências:
       pip install requests pillow tqdm rembg ddgs

  2. Coloque o arquivo CSV com os produtos na mesma pasta
     que este script. O CSV deve ter duas colunas:
       - nome_produto : usado para buscar a imagem na internet
       - nome_imagem  : usado para nomear o arquivo salvo

  3. Execute:
       python teste.py

  4. Para rodar o script no WSL2
        Primeiro crie o ambiente dentro do linux
            python3 -m venv venv
            source venv/bin/activate
        Depois rode os comandos de instalação dos pacotes normalmente
            pip install requests pillow tqdm rembg ddgs
            pip install "rembg[cpu]"

  ATENÇÃO: As imagens serão salvas em PNG (com fundo transparente).
           O formato JPG não suporta transparência.
=============================================================
"""

import csv
import logging
import os
import random
import re
import requests
import time
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image
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
LARGURA_MIN_PX  = 180                  # Ignora imagens muito pequenas
ALTURA_MIN_PX   = 180                  # Ignora imagens muito pequenas
PROPORCAO_MAX   = 5.0                  # Ignora banners/imagens muito esticadas
MAX_RESULTADOS_BUSCA = 30              # Quantidade de resultados avaliados por consulta
MIN_SCORE_IMAGEM = 18                  # Pontuação mínima para aceitar uma imagem
TERMO_EXTRA     = "foto produto embalagem"  # Termo extra para refinar a busca
LARGURA_FINAL_PX = 406                 # Largura final das imagens salvas
ALTURA_FINAL_PX  = 406                 # Altura final das imagens salvas
MARGEM_FINAL_PX  = 12                  # Margem transparente ao redor do produto
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

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "latin1")

ABREVIACOES_BUSCA = [
    (r"\bAGUA/SAL\b", "AGUA E SAL"),
    (r"\bS/AM\b", "SEM AMONIA"),
    (r"\bC/(\d+)\b", r"COM \1"),
    (r"\bBCO\b", "BRANCO"),
    (r"\bTTO\b", "TINTO"),
    (r"\bBISC\b", "BISCOITO"),
    (r"\bSALG\b", "SALGADO"),
    (r"\bCOND\b", "CONDICIONADOR"),
    (r"\bTINT\b", "TINTURA"),
    (r"\bCERV\b", "CERVEJA"),
    (r"\bLT\b", "LATA"),
    (r"\bGFA\b", "GARRAFA"),
    (r"\bCONS\b", "CONSERVA"),
    (r"\bCONG\b", "CONGELADO"),
    (r"\bRET\b", "RETANGULAR"),
    (r"\bTAMP\b", "TAMPA"),
    (r"\bACHOC\b", "ACHOCOLATADO"),
    (r"\bRACAO\b", "RACAO"),
    (r"\bTOALHA BANHO\b", "TOALHA DE BANHO"),
    (r"\bTOALHA UMED\b", "TOALHA UMEDECIDA"),
    (r"\bGARRAFA TERM\b", "GARRAFA TERMICA"),
    (r"\bLIMP PERF\b", "LIMPADOR PERFUMADO"),
    (r"\bLIMP PESADA\b", "LIMPADOR LIMPEZA PESADA"),
    (r"\bP FUSION\b", "POWER FUSION"),
    (r"\bLOURO ESC\b", "LOURO ESCURO"),
    (r"\bMALB\b", "MALBEC"),
    (r"\bCABERNET SAUV\b", "CABERNET SAUVIGNON"),
    (r"\bPINOT G\b", "PINOT GRIGIO"),
    (r"\bRIE\b", "RIESLING"),
]

STOPWORDS_BUSCA = {
    "a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em",
    "com", "sem", "para", "por", "un", "unidade", "pacote", "produto",
    "foto", "imagem",
}

TERMOS_NEGATIVOS = {
    "alamy", "clipart", "colorir", "desenho", "freepik", "icone", "logo",
    "manual", "molde", "pinterest", "pngtree", "receita", "shutterstock",
    "vetor", "wallpaper",
}

FONTES_CONFIAVEIS = {
    "amazon", "americanas", "belezanaweb", "carrefour", "drogaraia",
    "drogasil", "epocacosmeticos", "magazineluiza", "mercado livre",
    "mercadolivre", "pao de acucar", "paodeacucar", "supermercado",
}


@dataclass(frozen=True)
class CandidatoImagem:
    url: str
    score: int
    titulo: str = ""
    fonte: str = ""
    pagina: str = ""
    consulta: str = ""
    largura: int = 0
    altura: int = 0


def normalizar_espacos(texto: str) -> str:
    """Remove espaços duplicados sem mexer no conteúdo relevante."""
    return re.sub(r"\s+", " ", texto).strip()


def preparar_produto_para_consulta(produto: str) -> str:
    """Deixa o nome do cadastro mais legível para motores de busca."""
    texto = normalizar_espacos(produto)
    texto = re.sub(r"(?<=[A-Za-zÀ-ÿ])(?=\d)", " ", texto)
    texto = re.sub(r"(?<=\d)(?=[A-Za-zÀ-ÿ])", " ", texto)
    texto = re.sub(r"(\d+)\s*[xX]\s*(\d+)", r"\1x\2", texto)
    texto = re.sub(r"(\d+)\s+(ML|L|G|KG|W|V|T|UN|CM)\b", r"\1\2", texto, flags=re.IGNORECASE)
    return normalizar_espacos(texto)


def expandir_abreviacoes(produto: str) -> str:
    """Expande abreviações comuns do cadastro para melhorar a busca."""
    texto = normalizar_espacos(produto.upper())

    for padrao, substituto in ABREVIACOES_BUSCA:
        texto = re.sub(padrao, substituto, texto, flags=re.IGNORECASE)

    return preparar_produto_para_consulta(texto)


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparação sem acento, caixa ou pontuação."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("&", " e ")
    texto = re.sub(r"(\d+)[,.](\d+)", r"\1\2", texto)
    texto = re.sub(r"(?<=[a-wyz])(?=\d)", " ", texto)
    texto = re.sub(r"(?<=\d)(?=[a-wyz])", " ", texto)
    texto = re.sub(r"(\d+)\s*x\s*(\d+)", r"\1x\2", texto)
    texto = re.sub(r"(\d+)\s*(ml|l|g|kg|w|v|t|un|cm)\b", r"\1\2", texto)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return normalizar_espacos(texto)


def tokenizar_relevantes(produto: str) -> list[str]:
    """Extrai palavras que ajudam a diferenciar um produto de outro."""
    tokens = []

    for token in normalizar_texto(expandir_abreviacoes(produto)).split():
        if token in STOPWORDS_BUSCA:
            continue

        if len(token) < 3 and not any(c.isdigit() for c in token):
            continue

        if token not in tokens:
            tokens.append(token)

    return tokens


def inteiro_seguro(valor) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return 0


def dominio_de(url: str) -> str:
    dominio = urlparse(str(url)).netloc.lower()
    if dominio.startswith("www."):
        dominio = dominio[4:]
    return dominio


def pontuar_resultado(produto: str, resultado: dict) -> int:
    """Dá uma nota ao resultado usando metadados, não só a ordem do buscador."""
    campos = (
        resultado.get("title", ""),
        resultado.get("source", ""),
        resultado.get("url", ""),
        resultado.get("image", ""),
    )
    texto_original = " ".join(str(campo or "") for campo in campos)
    texto_normalizado = normalizar_texto(texto_original)
    tokens_texto = set(texto_normalizado.split())
    tokens_produto = tokenizar_relevantes(produto)

    if not tokens_produto:
        return 0

    tokens_encontrados = [token for token in tokens_produto if token in tokens_texto]
    cobertura = len(tokens_encontrados) / len(tokens_produto)
    score = len(tokens_encontrados) * 4 + int(cobertura * 20)

    consulta_original = normalizar_texto(preparar_produto_para_consulta(produto))
    consulta_expandida = normalizar_texto(expandir_abreviacoes(produto))

    if consulta_expandida and consulta_expandida in texto_normalizado:
        score += 25
    elif consulta_original and consulta_original in texto_normalizado:
        score += 20

    for token in tokens_produto:
        if any(c.isdigit() for c in token) and token not in tokens_texto:
            score -= 4

    if any(termo in texto_normalizado for termo in TERMOS_NEGATIVOS):
        score -= 12

    fonte_normalizada = normalizar_texto(
        f"{resultado.get('source', '')} "
        f"{dominio_de(resultado.get('url', ''))} "
        f"{dominio_de(resultado.get('image', ''))}"
    )
    if any(fonte in fonte_normalizada for fonte in FONTES_CONFIAVEIS):
        score += 6

    largura = inteiro_seguro(resultado.get("width"))
    altura = inteiro_seguro(resultado.get("height"))

    if largura and altura:
        menor = min(largura, altura)
        maior = max(largura, altura)

        if largura >= 500 and altura >= 500:
            score += 4
        elif largura >= LARGURA_MIN_PX and altura >= ALTURA_MIN_PX:
            score += 2

        if menor and maior / menor > PROPORCAO_MAX:
            score -= 6

        if largura < LARGURA_MIN_PX or altura < ALTURA_MIN_PX:
            score -= 8

    return max(score, 0)


def resumir_texto(texto: str, limite: int = 80) -> str:
    texto = normalizar_espacos(str(texto or ""))
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3].rstrip() + "..."


def resumir_candidato(candidato: CandidatoImagem) -> str:
    titulo = resumir_texto(candidato.titulo or candidato.pagina or candidato.url)
    fonte = resumir_texto(candidato.fonte or dominio_de(candidato.pagina) or "-", 35)
    return f"score={candidato.score} fonte={fonte} titulo='{titulo}'"


def montar_consultas_busca(produto: str) -> list[str]:
    """Monta consultas em ordem de precisão, com fallback menos rígido."""
    termos_base = []

    for termo in (expandir_abreviacoes(produto), preparar_produto_para_consulta(produto)):
        termo = termo.replace('"', "")
        if termo and termo not in termos_base:
            termos_base.append(termo)

    consultas = []
    for termo in termos_base:
        consultas.append(f'"{termo}" {TERMO_EXTRA}')
        consultas.append(f"{termo} {TERMO_EXTRA}")

    return list(dict.fromkeys(consultas))


def sanitizar_nome(nome: str) -> str:
    """Remove caracteres inválidos para nome de arquivo."""
    caracteres_invalidos = r'\/:*?"<>|'
    for c in caracteres_invalidos:
        nome = nome.replace(c, "_")
    return nome.strip()[:100]



def buscar_candidatos_imagens(produto: str, max_resultados: int = MAX_RESULTADOS_BUSCA) -> list[CandidatoImagem]:
    """
    Busca imagens e retorna candidatos ordenados por relevância.
    A pontuação evita aceitar automaticamente a primeira imagem do buscador.
    """
    consultas = montar_consultas_busca(produto)
    melhor_descartado = None

    for tentativa in range(3):
        try:
            candidatos = []
            urls_vistas = set()

            with DDGS(timeout=20) as ddgs:
                for consulta in consultas:
                    resultados = ddgs.images(
                        consulta,
                        region="br-pt",
                        safesearch="off",
                        type_image="photo",
                        max_results=max_resultados,
                    )

                    for resultado in resultados:
                        url = resultado.get("image")

                        if not url:
                            continue

                        if len(url) > 500:
                            continue

                        if url in urls_vistas:
                            continue

                        urls_vistas.add(url)
                        score = pontuar_resultado(produto, resultado)

                        candidato = CandidatoImagem(
                            url=url,
                            score=score,
                            titulo=str(resultado.get("title") or ""),
                            fonte=str(resultado.get("source") or ""),
                            pagina=str(resultado.get("url") or ""),
                            consulta=consulta,
                            largura=inteiro_seguro(resultado.get("width")),
                            altura=inteiro_seguro(resultado.get("height")),
                        )
                        candidatos.append(candidato)

            candidatos.sort(key=lambda c: c.score, reverse=True)
            candidatos_confiaveis = [c for c in candidatos if c.score >= MIN_SCORE_IMAGEM]

            if candidatos:
                melhor_descartado = candidatos[0]

            if candidatos_confiaveis:
                log.info(
                    f"🔎 Melhor candidato para '{produto}': "
                    f"{resumir_candidato(candidatos_confiaveis[0])}"
                )
                return candidatos_confiaveis

            if melhor_descartado:
                log.warning(
                    f"Nenhum candidato confiável para '{produto}'. "
                    f"Melhor encontrado: {resumir_candidato(melhor_descartado)}"
                )
                return []

            log.warning(f"Nenhum resultado de imagem encontrado para '{produto}'.")
            return []

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

        img = Image.open(BytesIO(conteudo)).convert("RGBA")
        largura, altura = img.size
        menor = min(largura, altura)
        maior = max(largura, altura)

        if largura < LARGURA_MIN_PX or altura < ALTURA_MIN_PX:
            return None

        if menor and maior / menor > PROPORCAO_MAX:
            return None

        return img

    except Exception:
        return None


def remover_fundo(img: Image.Image) -> Image.Image:
    """Remove o fundo da imagem usando rembg e retorna imagem com transparência."""
    buffer_entrada = BytesIO()
    img.save(buffer_entrada, format="PNG")
    buffer_entrada.seek(0)

    resultado = remove(buffer_entrada.read())
    return Image.open(BytesIO(resultado)).convert("RGBA")


def redimensionar_para_tamanho_final(img: Image.Image) -> Image.Image:
    """Centraliza a imagem em uma tela transparente de 406x406 sem deformar."""
    img = img.convert("RGBA")
    largura_final = LARGURA_FINAL_PX
    altura_final = ALTURA_FINAL_PX
    margem = max(0, MARGEM_FINAL_PX)

    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return Image.new("RGBA", (largura_final, altura_final), (255, 255, 255, 0))

    if bbox:
        img = img.crop(bbox)

    area_largura = max(1, largura_final - (margem * 2))
    area_altura = max(1, altura_final - (margem * 2))
    proporcao = min(area_largura / img.width, area_altura / img.height)
    nova_largura = max(1, round(img.width * proporcao))
    nova_altura = max(1, round(img.height * proporcao))

    filtro = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    img = img.resize((nova_largura, nova_altura), filtro)

    canvas = Image.new("RGBA", (largura_final, altura_final), (255, 255, 255, 0))
    posicao_x = (largura_final - nova_largura) // 2
    posicao_y = (altura_final - nova_altura) // 2
    canvas.alpha_composite(img, (posicao_x, posicao_y))
    return canvas


def ajustar_imagem_existente(caminho_img: Path) -> bool:
    """Garante que uma imagem já salva também fique no tamanho final."""
    try:
        with Image.open(caminho_img) as img:
            if img.size == (LARGURA_FINAL_PX, ALTURA_FINAL_PX):
                return False

            img_final = redimensionar_para_tamanho_final(img)
            img_final.save(caminho_img, "PNG")
            return True
    except Exception as e:
        log.warning(f"Não foi possível ajustar imagem existente '{caminho_img.name}': {e}")
        return False


def ler_produtos_csv(caminho: str) -> list:
    """Lê o CSV e retorna lista de tuplas (nome_para_buscar, nome_para_salvar)."""
    produtos = []
    linhas = None
    encoding_usado = None

    for encoding in CSV_ENCODINGS:
        try:
            with open(caminho, newline="", encoding=encoding) as f:
                linhas = list(csv.DictReader(f, delimiter=";"))
            encoding_usado = encoding
            break
        except UnicodeDecodeError:
            continue

    if linhas is None:
        raise ValueError(f"não foi possível ler o CSV com: {', '.join(CSV_ENCODINGS)}")

    log.info(f"📄 CSV lido com encoding: {encoding_usado}")

    for linha in linhas:
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
    redimensionadas = 0

    for nome_busca, nome_arquivo in tqdm(produtos, desc="Baixando imagens", unit="produto"):
        # Salva sempre como .png (transparência exige PNG)
        nome_final = sanitizar_nome(nome_arquivo)
        nome_final = re.sub(r'\.(jpg|jpeg|png|webp)$', '', nome_final, flags=re.IGNORECASE)
        nome_final += ".png"

        caminho_img = pasta / nome_final

        # Pula se já foi baixada
        if caminho_img.exists():
            if ajustar_imagem_existente(caminho_img):
                redimensionadas += 1
                log.info(f"📐 Imagem ajustada para 406x406: {nome_final}")

            ja_existia += 1
            continue

        candidatos = buscar_candidatos_imagens(nome_busca)

        baixou = False
        for candidato in candidatos:
            img = baixar_imagem(candidato.url)
            if img is None:
                continue

            try:
                log.info(
                    f"🔄 Removendo fundo: '{nome_busca}' "
                    f"({resumir_candidato(candidato)})..."
                )
                img_sem_fundo = remover_fundo(img)
                img_final = redimensionar_para_tamanho_final(img_sem_fundo)
                img_final.save(caminho_img, "PNG")
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
    log.info(f"   📐 Ajustadas 406x406   : {redimensionadas}")
    log.info(f"   ✘ Falhas               : {falha}")
    log.info(f"   📁 Imagens salvas em   : {pasta.resolve()}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
