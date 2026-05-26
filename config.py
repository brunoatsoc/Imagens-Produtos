import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


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


def obter_env_float(
    nome: str,
    padrao: float,
    minimo: Optional[float] = None,
    maximo: Optional[float] = None,
) -> float:
    """Le e valida variaveis de ambiente numericas com casas decimais."""
    valor = os.getenv(nome, "")

    if not valor.strip():
        numero = padrao
    else:
        try:
            numero = float(valor.strip().replace(",", "."))
        except ValueError as e:
            raise ValueError(
                f"{nome} deve ser um numero decimal; valor recebido: {valor!r}"
            ) from e

    if minimo is not None and numero < minimo:
        raise ValueError(f"{nome} deve ser maior ou igual a {minimo}; valor recebido: {numero}")

    if maximo is not None and numero > maximo:
        raise ValueError(f"{nome} deve ser menor ou igual a {maximo}; valor recebido: {numero}")

    return numero


def resolver_pasta_saida(caminho: str) -> Path:
    """Resolve a pasta de saida a partir da pasta do script/executavel."""
    caminho = str(caminho or "").strip() or "imagens_produtos"
    pasta = Path(caminho).expanduser()

    if not pasta.is_absolute():
        pasta = BASE_DIR / pasta

    return pasta


def configurar_logging() -> None:
    pasta_log = BASE_DIR / "log"
    pasta_log.mkdir(parents=True, exist_ok=True)
    nome_arquivo_log = f"intellisysimages_{datetime.now():%Y%m%d_%H%M%S}.log"
    caminho_arquivo_log = pasta_log / nome_arquivo_log

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(caminho_arquivo_log, encoding="utf-8"),
        ]
    )

    logging.getLogger(__name__).info(f"Logs salvos em: {caminho_arquivo_log.resolve()}")


carregar_dotenv()

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
PASTA_SAIDA     = os.getenv("PASTA_SAIDA", "imagens_produtos")   # Pasta onde as imagens serão salvas
DELAY_MIN       = 1.5                  # Espera mínima entre buscas (segundos)
DELAY_MAX       = 3.5                  # Espera máxima entre buscas (segundos)
TAMANHO_MIN_KB  = 5                    # Ignora imagens menores que X KB
LARGURA_MIN_PX  = 180                  # Ignora imagens muito pequenas
ALTURA_MIN_PX   = 180                  # Ignora imagens muito pequenas
PROPORCAO_MAX   = 5.0                  # Ignora banners/imagens muito esticadas
MAX_RESULTADOS_BUSCA = 30              # Quantidade de resultados avaliados por consulta
MIN_SCORE_IMAGEM = obter_env_int("MIN_SCORE_IMAGEM", 35, minimo=0)  # Pontuação mínima para aceitar uma imagem
MIN_COBERTURA_TOKENS = obter_env_float("MIN_COBERTURA_TOKENS", 0.55, minimo=0.0, maximo=1.0)
MIN_COBERTURA_IDENTIDADE = obter_env_float("MIN_COBERTURA_IDENTIDADE", 0.60, minimo=0.0, maximo=1.0)
TERMO_EXTRA     = "foto produto embalagem"  # Termo extra para refinar a busca
PRODUTOS_POR_LOTE = obter_env_int("PRODUTOS_POR_LOTE", 100, minimo=1)  # Quantidade de produtos consultados por vez
LARGURA_FINAL_PX = obter_env_int("LARGURA_FINAL_PX", 406, minimo=1)  # Largura final das imagens salvas
ALTURA_FINAL_PX  = obter_env_int("ALTURA_FINAL_PX", 406, minimo=1)   # Altura final das imagens salvas
MARGEM_FINAL_PX  = 12                  # Margem ao redor da imagem no canvas final

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

configurar_logging()
