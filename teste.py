"""
=============================================================
  Script: Buscador de Imagens de Produtos para Mercado
=============================================================
  Como usar:
  1. Instale as dependências:
       pip install requests pillow tqdm rembg ddgs oracledb

  2. Configure o acesso ao banco no arquivo .env, na mesma pasta do script:
       DB_PROVIDER=oracle
       DB_USER=usuario
       DB_PASSWORD=senha
       DB_DSN=host:porta/servico
       TABELA_OFERTAS=CLIENTE.WSOFERTASATIVAS
       TABELA_IMAGENS=CLIENTE.PRODUTOSIMAGENS
       LARGURA_FINAL_PX=406
       ALTURA_FINAL_PX=406

     Por padrão o script usa Oracle via python-oracledb.
     Para usar ODBC, configure:
       DB_PROVIDER=odbc
       ODBC_CONNECTION_STRING=DSN=meu_dsn;UID=usuario;PWD=senha

  3. Execute:
       python teste.py

  4. Para rodar o script no WSL2
        Primeiro crie o ambiente dentro do linux
            python3 -m venv venv
            source venv/bin/activate
        Depois rode os comandos de instalação dos pacotes normalmente
            pip install requests pillow tqdm rembg ddgs oracledb
            pip install "rembg[cpu]"

  ATENÇÃO: As imagens serão salvas em PNG (com fundo transparente).
           O formato JPG não suporta transparência.
=============================================================
"""

import logging
import os
import random
import re
import requests
import sys
import time
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from PIL import Image
from tqdm import tqdm
from rembg import remove
from ddgs import DDGS


if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def carregar_dotenv(caminho_env: Optional[Path] = None) -> None:
    """
    Carrega variaveis de ambiente de um arquivo .env simples.
    Variaveis ja existentes no sistema prevalecem sobre o arquivo.
    """
    caminho_env = caminho_env or BASE_DIR / ".env"

    if not caminho_env.exists():
        return

    for linha in caminho_env.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()

        if not linha or linha.startswith("#"):
            continue

        if linha.startswith("export "):
            linha = linha.removeprefix("export ").strip()

        if "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)
        chave = chave.strip()

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", chave):
            continue

        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        else:
            valor = valor.split(" #", 1)[0].strip()

        os.environ.setdefault(chave, valor)


def obter_env_int(nome: str, padrao: int, minimo: Optional[int] = None) -> int:
    """Le e valida variaveis de ambiente inteiras."""
    valor = os.getenv(nome, "")

    if not valor.strip():
        numero = padrao
    else:
        try:
            numero = int(valor.strip())
        except ValueError as e:
            raise ValueError(
                f"{nome} deve ser um numero inteiro; valor recebido: {valor!r}"
            ) from e

    if minimo is not None and numero < minimo:
        raise ValueError(f"{nome} deve ser maior ou igual a {minimo}; valor recebido: {numero}")

    return numero


def resolver_pasta_saida(caminho: str) -> Path:
    """Resolve a pasta de saida a partir da pasta do script/executavel."""
    caminho = str(caminho or "").strip() or "imagens_produtos"
    pasta = Path(caminho).expanduser()

    if not pasta.is_absolute():
        pasta = BASE_DIR / pasta

    return pasta


carregar_dotenv()

# ─────────────────────────────────────────────
#  ⚙️  CONFIGURAÇÕES — AJUSTE AQUI
# ─────────────────────────────────────────────
PASTA_SAIDA     = os.getenv("PASTA_SAIDA", "imagens_produtos")   # Pasta onde as imagens serão salvas
DELAY_MIN       = 1.5                  # Espera mínima entre buscas (segundos)
DELAY_MAX       = 3.5                  # Espera máxima entre buscas (segundos)
TAMANHO_MIN_KB  = 5                    # Ignora imagens menores que X KB
LARGURA_MIN_PX  = 180                  # Ignora imagens muito pequenas
ALTURA_MIN_PX   = 180                  # Ignora imagens muito pequenas
PROPORCAO_MAX   = 5.0                  # Ignora banners/imagens muito esticadas
MAX_RESULTADOS_BUSCA = 30              # Quantidade de resultados avaliados por consulta
MIN_SCORE_IMAGEM = 18                  # Pontuação mínima para aceitar uma imagem
TERMO_EXTRA     = "foto produto embalagem"  # Termo extra para refinar a busca
PRODUTOS_POR_LOTE = obter_env_int("PRODUTOS_POR_LOTE", 100, minimo=1)  # Quantidade de produtos consultados por vez
LARGURA_FINAL_PX = obter_env_int("LARGURA_FINAL_PX", 406, minimo=1)  # Largura final das imagens salvas
ALTURA_FINAL_PX  = obter_env_int("ALTURA_FINAL_PX", 406, minimo=1)   # Altura final das imagens salvas
MARGEM_FINAL_PX  = 12                  # Margem transparente ao redor do produto

# Banco de dados
DB_PROVIDER     = os.getenv("DB_PROVIDER", "oracle").strip().lower()
DB_USER         = os.getenv("DB_USER", "")
DB_PASSWORD     = os.getenv("DB_PASSWORD", "")
DB_DSN          = os.getenv("DB_DSN", "")
DB_CLIENT_LIB_DIR = os.getenv("DB_CLIENT_LIB_DIR", "")
DB_CONNECT_TIMEOUT = obter_env_int("DB_CONNECT_TIMEOUT", 30, minimo=1)
ODBC_CONNECTION_STRING = os.getenv("ODBC_CONNECTION_STRING", "")

TABELA_OFERTAS  = os.getenv("TABELA_OFERTAS", "")
TABELA_IMAGENS  = os.getenv("TABELA_IMAGENS", "")
COLUNA_CODIGO_OFERTA = os.getenv("COLUNA_CODIGO_OFERTA", "PROCODBASE")
COLUNA_DESCRICAO_OFERTA = os.getenv("COLUNA_DESCRICAO_OFERTA", "PRODESCRICAO")
COLUNA_CODIGO_IMAGEM = os.getenv("COLUNA_CODIGO_IMAGEM", "PROIMGCODBASE")
USUARIO_ALTERACAO_IMAGEM = os.getenv("USUARIO_ALTERACAO_IMAGEM", "BUSCADOR_IMAGENS")
FLAG_EVTCOM_AUTOMATICO = obter_env_int("FLAG_EVTCOM_AUTOMATICO", 1)
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
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
    """Centraliza a imagem no tamanho final configurado, sem deformar."""
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


def validar_identificador_sql(nome: str, campo: str) -> str:
    """
    Valida nomes configuráveis de tabelas/colunas antes de montar a consulta.
    Permite nomes simples ou qualificados por schema, como USUARIO.TABELA.
    """
    identificador = str(nome or "").strip().upper()

    if not identificador:
        raise ValueError(f"configure {campo} no .env")

    if not re.fullmatch(r"[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)*", identificador):
        raise ValueError(f"identificador SQL inválido em {campo}: {nome!r}")

    return identificador


def montar_sql_base_produtos_sem_imagem() -> str:
    """Monta a base do SELECT das ofertas ativas que ainda não possuem imagem."""
    tabela_ofertas = validar_identificador_sql(TABELA_OFERTAS, "TABELA_OFERTAS")
    tabela_imagens = validar_identificador_sql(TABELA_IMAGENS, "TABELA_IMAGENS")
    coluna_codigo_oferta = validar_identificador_sql(COLUNA_CODIGO_OFERTA, "COLUNA_CODIGO_OFERTA")
    coluna_descricao_oferta = validar_identificador_sql(
        COLUNA_DESCRICAO_OFERTA,
        "COLUNA_DESCRICAO_OFERTA",
    )
    coluna_codigo_imagem = validar_identificador_sql(COLUNA_CODIGO_IMAGEM, "COLUNA_CODIGO_IMAGEM")

    return f"""
        SELECT DISTINCT
               o.{coluna_codigo_oferta} AS procodbase,
               o.{coluna_descricao_oferta} AS prodescricao
          FROM {tabela_ofertas} o
          LEFT JOIN {tabela_imagens} i
            ON i.{coluna_codigo_imagem} = o.{coluna_codigo_oferta}
         WHERE i.{coluna_codigo_imagem} IS NULL
           AND o.{coluna_codigo_oferta} IS NOT NULL
           AND o.{coluna_descricao_oferta} IS NOT NULL
    """


def montar_sql_produtos_sem_imagem() -> str:
    """Monta o SELECT completo das ofertas ativas que ainda não possuem imagem."""
    return f"""
        {montar_sql_base_produtos_sem_imagem()}
         ORDER BY prodescricao, procodbase
    """


def montar_sql_lote_produtos_sem_imagem() -> str:
    """Monta o SELECT paginado por chave para buscar produtos em lotes."""
    return f"""
        SELECT procodbase, prodescricao
          FROM (
            SELECT procodbase, prodescricao
              FROM (
                {montar_sql_base_produtos_sem_imagem()}
              )
             WHERE (
                   :ultima_descricao IS NULL
                OR prodescricao > :ultima_descricao
                OR (prodescricao = :ultima_descricao AND procodbase > :ultimo_codigo)
             )
             ORDER BY prodescricao, procodbase
          )
         WHERE ROWNUM <= :limite_lote
    """


def conectar_banco():
    """Abre a conexão com o banco configurado por variáveis de ambiente."""
    if DB_PROVIDER == "oracle":
        try:
            import oracledb
        except ImportError as e:
            raise RuntimeError(
                "dependência 'oracledb' não instalada. "
                "Instale com: pip install oracledb"
            ) from e

        if not DB_USER or not DB_PASSWORD or not DB_DSN:
            raise ValueError("configure DB_USER, DB_PASSWORD e DB_DSN no .env para conectar no Oracle")

        if DB_CLIENT_LIB_DIR:
            try:
                oracledb.init_oracle_client(lib_dir=DB_CLIENT_LIB_DIR)
            except Exception as e:
                log.warning(f"Não foi possível inicializar Oracle Client: {e}")

        return oracledb.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            dsn=DB_DSN,
        )

    if DB_PROVIDER == "odbc":
        try:
            import pyodbc
        except ImportError as e:
            raise RuntimeError(
                "dependência 'pyodbc' não instalada. "
                "Instale com: pip install pyodbc"
            ) from e

        if not ODBC_CONNECTION_STRING:
            raise ValueError("configure ODBC_CONNECTION_STRING no .env para conectar via ODBC")

        return pyodbc.connect(ODBC_CONNECTION_STRING, timeout=DB_CONNECT_TIMEOUT)

    raise ValueError("DB_PROVIDER deve ser 'oracle' ou 'odbc'")


def normalizar_linhas_produtos(linhas) -> list[tuple[str, str]]:
    produtos = []

    for procodbase, prodescricao in linhas:
        nome_busca = str(prodescricao or "").strip()
        nome_arquivo = str(procodbase or "").strip()

        if not nome_busca or not nome_arquivo:
            continue

        produtos.append((nome_busca, nome_arquivo))

    return produtos


def ler_lote_produtos_banco(
    ultimo_produto: Optional[tuple[str, str]],
    tamanho_lote: int,
) -> list[tuple[str, str]]:
    """
    Busca um lote de ofertas ativas sem imagem no Oracle.
    Retorna tuplas (prodescricao_para_buscar, procodbase_para_salvar).
    """
    sql = montar_sql_lote_produtos_sem_imagem()
    parametros = {
        "ultima_descricao": ultimo_produto[0] if ultimo_produto else None,
        "ultimo_codigo": ultimo_produto[1] if ultimo_produto else None,
        "limite_lote": tamanho_lote,
    }

    conexao = conectar_banco()
    try:
        cursor = conexao.cursor()
        cursor.arraysize = tamanho_lote
        try:
            cursor.execute(sql, parametros)
            return normalizar_linhas_produtos(cursor)
        finally:
            cursor.close()
    finally:
        conexao.close()


def iterar_lotes_produtos_banco(tamanho_lote: int):
    """
    Busca produtos sem imagem em lotes, sem manter a lista completa em memoria.
    No Oracle, cada lote usa uma consulta limitada; em outros provedores,
    usa fetchmany para não carregar todos os registros no Python de uma vez.
    """
    log.info(f"🗄️  Consultando ofertas ativas sem imagem em lotes de até {tamanho_lote} produtos...")

    if DB_PROVIDER == "oracle":
        ultimo_produto = None

        while True:
            produtos = ler_lote_produtos_banco(ultimo_produto, tamanho_lote)

            if not produtos:
                break

            yield produtos
            ultimo_produto = produtos[-1]

        return

    sql = montar_sql_produtos_sem_imagem()
    conexao = conectar_banco()
    try:
        cursor = conexao.cursor()
        cursor.arraysize = tamanho_lote
        try:
            cursor.execute(sql)

            while True:
                linhas = cursor.fetchmany(tamanho_lote)

                if not linhas:
                    break

                produtos = normalizar_linhas_produtos(linhas)

                if produtos:
                    yield produtos
        finally:
            cursor.close()
    finally:
        conexao.close()


def ler_produtos_banco() -> list[tuple[str, str]]:
    """
    Busca no banco as ofertas ativas sem imagem.
    Mantida para compatibilidade; o fluxo principal usa lotes.
    """
    produtos = []

    for lote in iterar_lotes_produtos_banco(PRODUTOS_POR_LOTE):
        produtos.extend(lote)

    return produtos


def montar_sql_insert_imagem() -> str:
    """Monta o INSERT que grava a imagem baixada na tabela de imagens."""
    tabela_imagens = validar_identificador_sql(TABELA_IMAGENS, "TABELA_IMAGENS")
    coluna_codigo_imagem = validar_identificador_sql(COLUNA_CODIGO_IMAGEM, "COLUNA_CODIGO_IMAGEM")

    return f"""
        INSERT INTO {tabela_imagens} (
            {coluna_codigo_imagem},
            PROIMGARQIMAGEM,
            PROIMGNOMEARQUIVO,
            PROIMGUSRALTERACAO,
            PROIMGDTAALTERACAO,
            PROIMGFLAGEVTCOMAUTOMATICO,
            PROIMGDTAEVTCOMAUTOMATICO
        )
        VALUES (
            :codigo,
            :imagem,
            :nome_arquivo,
            :usuario,
            SYSDATE,
            :flag_automatico,
            SYSDATE
        )
    """


def erro_chave_duplicada(erro: Exception) -> bool:
    """Identifica erro de PK/unique para contar como imagem já existente."""
    primeiro_arg = erro.args[0] if getattr(erro, "args", None) else None
    codigo = getattr(primeiro_arg, "code", None)
    return codigo == 1 or "ORA-00001" in str(erro)


def configurar_bind_blob(cursor) -> None:
    """Ajuda o python-oracledb a tratar o bind da imagem como BLOB."""
    if DB_PROVIDER != "oracle":
        return

    try:
        import oracledb

        cursor.setinputsizes(imagem=oracledb.DB_TYPE_BLOB)
    except Exception as e:
        log.debug(f"Não foi possível configurar bind BLOB explicitamente: {e}")


def preparar_codigo_banco(codigo: str) -> int:
    """Converte o PROCODBASE para NUMBER(18,0), como a tabela espera."""
    codigo_limpo = str(codigo or "").strip()

    if not re.fullmatch(r"\d+", codigo_limpo):
        raise ValueError(f"PROCODBASE inválido para inserir imagem: {codigo!r}")

    return int(codigo_limpo)


def registrar_imagem_pronta(
    imagens_prontas: dict[int, Path],
    codigo: str,
    caminho_img: Path,
) -> None:
    """Guarda uma imagem pronta para ser inserida no banco ao final."""
    if not caminho_img.exists():
        return

    try:
        imagens_prontas[preparar_codigo_banco(codigo)] = caminho_img
    except ValueError as e:
        log.warning(f"{e}. Arquivo ignorado no insert: {caminho_img.name}")


def inserir_imagens_banco(imagens_prontas: dict[int, Path]) -> tuple[int, int, int]:
    """
    Insere no banco as imagens geradas/localizadas.
    Retorna (inseridas, ja_existiam_no_banco, falhas).
    """
    if not imagens_prontas:
        return 0, 0, 0

    sql = montar_sql_insert_imagem()
    inseridas = 0
    ja_existiam = 0
    falhas = 0

    log.info(f"🗄️  Inserindo {len(imagens_prontas)} imagens na tabela {TABELA_IMAGENS}...")

    conexao = conectar_banco()
    try:
        cursor = conexao.cursor()
        try:
            configurar_bind_blob(cursor)

            for codigo, caminho_img in imagens_prontas.items():
                try:
                    imagem_bytes = caminho_img.read_bytes()
                    nome_arquivo = caminho_img.name[:50]

                    cursor.execute(
                        sql,
                        {
                            "codigo": codigo,
                            "imagem": imagem_bytes,
                            "nome_arquivo": nome_arquivo,
                            "usuario": USUARIO_ALTERACAO_IMAGEM[:50],
                            "flag_automatico": FLAG_EVTCOM_AUTOMATICO,
                        },
                    )
                    inseridas += 1
                except Exception as e:
                    if erro_chave_duplicada(e):
                        ja_existiam += 1
                        continue

                    falhas += 1
                    log.warning(
                        f"Não foi possível inserir '{caminho_img.name}' "
                        f"(PROCODBASE={codigo}) no banco: {e}"
                    )

            conexao.commit()
        finally:
            cursor.close()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()

    return inseridas, ja_existiam, falhas


def main():
    pasta = resolver_pasta_saida(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)
    tamanho_final = f"{LARGURA_FINAL_PX}x{ALTURA_FINAL_PX}"

    log.info(f"ℹ️  As imagens serão salvas em PNG com fundo transparente no tamanho {tamanho_final}.")
    log.info(f"📁 Pasta de saída das imagens: {pasta.resolve()}")

    sucesso    = 0
    falha      = 0
    ja_existia = 0
    redimensionadas = 0
    total_produtos = 0
    inseridas_banco = 0
    ja_existiam_banco = 0
    falhas_banco = 0

    for numero_lote, produtos in enumerate(iterar_lotes_produtos_banco(PRODUTOS_POR_LOTE), start=1):
        total_produtos += len(produtos)
        imagens_prontas: dict[int, Path] = {}

        log.info(f"✅ Lote {numero_lote}: {len(produtos)} ofertas ativas sem imagem encontradas no banco.")

        for nome_busca, nome_arquivo in tqdm(produtos, desc=f"Baixando lote {numero_lote}", unit="produto"):
            # Salva sempre como .png (transparência exige PNG)
            nome_final = sanitizar_nome(nome_arquivo)
            nome_final = re.sub(r'\.(jpg|jpeg|png|webp)$', '', nome_final, flags=re.IGNORECASE)
            nome_final += ".png"

            caminho_img = pasta / nome_final

            # Pula se já foi baixada
            if caminho_img.exists():
                if ajustar_imagem_existente(caminho_img):
                    redimensionadas += 1
                    log.info(f"📐 Imagem ajustada para {tamanho_final}: {nome_final}")

                ja_existia += 1
                registrar_imagem_pronta(imagens_prontas, nome_arquivo, caminho_img)
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
                    registrar_imagem_pronta(imagens_prontas, nome_arquivo, caminho_img)
                    break
                except Exception as e:
                    log.warning(f"Erro ao remover fundo de '{nome_busca}': {e}")
                    continue

            if not baixou:
                log.warning(f"✘ Sem imagem para: '{nome_busca}' (arquivo esperado: {nome_final})")
                falha += 1

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        inseridas_lote, ja_existiam_lote, falhas_lote = inserir_imagens_banco(imagens_prontas)
        inseridas_banco += inseridas_lote
        ja_existiam_banco += ja_existiam_lote
        falhas_banco += falhas_lote

    log.info("=" * 50)
    log.info(f"🎉 CONCLUÍDO!")
    log.info(f"   ✅ Produtos processados: {total_produtos}")
    log.info(f"   ✔ Baixados com sucesso : {sucesso}")
    log.info(f"   ⏭ Já existiam         : {ja_existia}")
    log.info(f"   📐 Ajustadas {tamanho_final}   : {redimensionadas}")
    log.info(f"   ✘ Falhas               : {falha}")
    log.info(f"   🗄️  Inseridas no banco : {inseridas_banco}")
    log.info(f"   🗄️  Já estavam no banco: {ja_existiam_banco}")
    log.info(f"   🗄️  Falhas no banco    : {falhas_banco}")
    log.info(f"   📁 Imagens salvas em   : {pasta.resolve()}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
