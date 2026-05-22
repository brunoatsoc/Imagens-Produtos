import logging
import random
import re
import requests
import time
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

from PIL import Image
from ddgs import DDGS

from config import (
    ALTURA_MIN_PX,
    LARGURA_MIN_PX,
    MAX_RESULTADOS_BUSCA,
    MIN_COBERTURA_IDENTIDADE,
    MIN_COBERTURA_TOKENS,
    MIN_SCORE_IMAGEM,
    PROPORCAO_MAX,
    TAMANHO_MIN_KB,
    TERMO_EXTRA,
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
    "foto", "imagem", "unidades",
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

TERMOS_GENERICOS_IDENTIDADE = STOPWORDS_BUSCA | {
    "achocolatado", "agua", "alimento", "alimentos", "anel", "aneis",
    "bebida", "bebidas", "biscoito", "bolacha", "caixa", "cerveja",
    "cebola", "coco", "condicionador", "congelada", "congelado",
    "detergente", "embalagem", "frasco", "frango", "garrafa", "kit",
    "lasanha", "lata", "limpador", "pastilha", "perfumado", "po",
    "pote", "refresco", "sache", "salgada", "salgado", "sanitario",
    "termica", "termico", "toalha", "umedecida", "umedecido", "vinho",
}


@dataclass(frozen=True)
class AnaliseRelevancia:
    tokens_produto: tuple[str, ...]
    tokens_encontrados: tuple[str, ...]
    tokens_identidade: tuple[str, ...]
    tokens_identidade_encontrados: tuple[str, ...]
    tokens_medida: tuple[str, ...]
    tokens_medida_encontrados: tuple[str, ...]
    cobertura: float
    cobertura_identidade: float
    motivo_rejeicao: str = ""


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
    texto = re.sub(r"(?<=[A-Za-zÀ-ÿ])[./](?=[A-Za-zÀ-ÿ])", " ", texto)
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


def variantes_token(token: str) -> set[str]:
    """Gera pequenas variações para comparar plural/singular sem stemming pesado."""
    variantes = {token}

    if len(token) > 4 and token.endswith("s"):
        variantes.add(token[:-1])
    elif len(token) > 4:
        variantes.add(f"{token}s")

    return variantes


def token_presente(token: str, tokens_texto: set[str]) -> bool:
    """Verifica se um token do produto aparece nos metadados do resultado."""
    if variantes_token(token) & tokens_texto:
        return True

    if token.isdigit():
        return any(re.fullmatch(rf"{re.escape(token)}(?:un|und|unidade|unidades)?", t) for t in tokens_texto)

    return False


def token_e_medida(token: str) -> bool:
    return any(c.isdigit() for c in token)


def tokens_de_identidade(tokens_produto: list[str]) -> list[str]:
    """Separa marca/linha/variante de termos de categoria e embalagem."""
    return [
        token
        for token in tokens_produto
        if not token_e_medida(token) and token not in TERMOS_GENERICOS_IDENTIDADE
    ]


def definir_motivo_rejeicao(
    tokens_produto: list[str],
    tokens_identidade: list[str],
    tokens_medida: list[str],
    tokens_encontrados: list[str],
    tokens_identidade_encontrados: list[str],
    tokens_medida_encontrados: list[str],
    cobertura: float,
    cobertura_identidade: float,
) -> str:
    """Aplica os cortes mínimos antes da pontuação final."""
    if not tokens_produto:
        return "sem tokens do produto"

    if tokens_medida and len(tokens_medida_encontrados) < len(tokens_medida):
        return "medida ausente ou divergente"

    if tokens_identidade and not tokens_identidade_encontrados:
        return "sem token de identidade"

    if tokens_identidade and cobertura_identidade < MIN_COBERTURA_IDENTIDADE:
        return "baixa cobertura de identidade"

    if len(tokens_produto) >= 4 and cobertura < MIN_COBERTURA_TOKENS:
        return "baixa cobertura geral"

    return ""


def analisar_relevancia_resultado(produto: str, resultado: dict) -> AnaliseRelevancia:
    """Compara a descrição do produto com os metadados retornados pelo buscador."""
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
    tokens_identidade = tokens_de_identidade(tokens_produto)
    tokens_medida = [token for token in tokens_produto if token_e_medida(token)]
    tokens_encontrados = [token for token in tokens_produto if token_presente(token, tokens_texto)]
    tokens_identidade_encontrados = [
        token for token in tokens_identidade if token_presente(token, tokens_texto)
    ]
    tokens_medida_encontrados = [
        token for token in tokens_medida if token_presente(token, tokens_texto)
    ]
    cobertura = len(tokens_encontrados) / len(tokens_produto) if tokens_produto else 0
    cobertura_identidade = (
        len(tokens_identidade_encontrados) / len(tokens_identidade)
        if tokens_identidade
        else 1
    )
    motivo_rejeicao = definir_motivo_rejeicao(
        tokens_produto,
        tokens_identidade,
        tokens_medida,
        tokens_encontrados,
        tokens_identidade_encontrados,
        tokens_medida_encontrados,
        cobertura,
        cobertura_identidade,
    )

    return AnaliseRelevancia(
        tokens_produto=tuple(tokens_produto),
        tokens_encontrados=tuple(tokens_encontrados),
        tokens_identidade=tuple(tokens_identidade),
        tokens_identidade_encontrados=tuple(tokens_identidade_encontrados),
        tokens_medida=tuple(tokens_medida),
        tokens_medida_encontrados=tuple(tokens_medida_encontrados),
        cobertura=cobertura,
        cobertura_identidade=cobertura_identidade,
        motivo_rejeicao=motivo_rejeicao,
    )


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


def pontuar_resultado(
    produto: str,
    resultado: dict,
    analise: AnaliseRelevancia | None = None,
) -> int:
    """Dá uma nota ao resultado usando metadados, não só a ordem do buscador."""
    analise = analise or analisar_relevancia_resultado(produto, resultado)

    if analise.motivo_rejeicao:
        return 0

    campos = (
        resultado.get("title", ""),
        resultado.get("source", ""),
        resultado.get("url", ""),
        resultado.get("image", ""),
    )
    texto_original = " ".join(str(campo or "") for campo in campos)
    texto_normalizado = normalizar_texto(texto_original)
    score = len(analise.tokens_encontrados) * 5 + int(analise.cobertura * 25)
    score += len(analise.tokens_identidade_encontrados) * 6
    score += int(analise.cobertura_identidade * 15)
    score += len(analise.tokens_medida_encontrados) * 5

    consulta_original = normalizar_texto(preparar_produto_para_consulta(produto))
    consulta_expandida = normalizar_texto(expandir_abreviacoes(produto))

    if consulta_expandida and consulta_expandida in texto_normalizado:
        score += 25
    elif consulta_original and consulta_original in texto_normalizado:
        score += 20

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


def buscar_candidatos_imagens(produto: str, max_resultados: int = MAX_RESULTADOS_BUSCA) -> list[CandidatoImagem]:
    """
    Busca imagens e retorna candidatos ordenados por relevância.
    A pontuação evita aceitar automaticamente a primeira imagem do buscador.
    """
    consultas = montar_consultas_busca(produto)
    melhor_descartado = None
    log.info(f"Buscando imagem para produto '{produto}'. Consultas: {', '.join(consultas)}")

    for tentativa in range(3):
        try:
            candidatos = []
            urls_vistas = set()

            with DDGS(timeout=20) as ddgs:
                descartes_por_motivo = {}

                for consulta in consultas:
                    resultados = ddgs.images(
                        consulta,
                        region="br-pt",
                        safesearch="moderate",
                        type_image="photo",
                        max_results=max_resultados,
                    )

                    resultados_consulta = 0
                    candidatos_consulta = 0
                    for resultado in resultados:
                        resultados_consulta += 1
                        url = resultado.get("image")

                        if not url:
                            continue

                        if len(url) > 500:
                            continue

                        if url in urls_vistas:
                            continue

                        urls_vistas.add(url)
                        analise = analisar_relevancia_resultado(produto, resultado)
                        score = pontuar_resultado(produto, resultado, analise)

                        if analise.motivo_rejeicao:
                            descartes_por_motivo[analise.motivo_rejeicao] = (
                                descartes_por_motivo.get(analise.motivo_rejeicao, 0) + 1
                            )

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
                        candidatos_consulta += 1

                    log.info(
                        f"Consulta '{consulta}' para '{produto}' retornou "
                        f"{resultados_consulta} resultado(s), "
                        f"{candidatos_consulta} candidato(s) válido(s) para pontuação."
                    )

            candidatos.sort(key=lambda c: c.score, reverse=True)
            candidatos_confiaveis = [c for c in candidatos if c.score >= MIN_SCORE_IMAGEM]
            log.info(
                f"Resultado da busca para '{produto}': "
                f"{len(candidatos)} candidato(s) avaliado(s), "
                f"{len(candidatos_confiaveis)} confiável(is)."
            )

            if descartes_por_motivo:
                resumo_descartes = ", ".join(
                    f"{qtd} por {motivo}"
                    for motivo, qtd in sorted(
                        descartes_por_motivo.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                )
                log.info(f"Candidatos descartados para '{produto}': {resumo_descartes}.")

            if candidatos:
                melhor_descartado = candidatos[0]

            if candidatos_confiaveis:
                log.info(
                    f"Melhor candidato para '{produto}': "
                    f"{resumir_candidato(candidatos_confiaveis[0])}"
                )
                return candidatos_confiaveis

            if melhor_descartado:
                log.warning(
                    f"Nenhum candidato confiável para '{produto}'. "
                    f"Melhor encontrado: {resumir_candidato(melhor_descartado)}"
                )
                log.warning(f"Imagem não encontrada para '{produto}': nenhum candidato atingiu a pontuação mínima.")
                return []

            log.warning(f"Nenhum resultado de imagem encontrado para '{produto}'.")
            log.warning(f"Imagem não encontrada para '{produto}': busca não retornou resultados.")
            return []

        except Exception as e:
            log.warning(
                f"Tentativa {tentativa + 1}/3 falhou para "
                f"'{produto}': {e}",
                exc_info=True,
            )

            # espera progressiva
            time.sleep(random.uniform(5, 12))

    return []


def baixar_imagem(url: str) -> Image.Image | None:
    """Baixa uma imagem e retorna o objeto PIL, ou None em caso de falha."""
    headers = random.choice(HEADERS_LIST)
    log.info(f"Baixando imagem candidata: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        conteudo = resp.content

        if len(conteudo) < TAMANHO_MIN_KB * 1024:
            log.warning(
                f"Imagem não encontrada/descartada em {url}: "
                f"arquivo com {len(conteudo) // 1024} KB, mínimo {TAMANHO_MIN_KB} KB."
            )
            return None

        img = Image.open(BytesIO(conteudo)).convert("RGBA")
        largura, altura = img.size
        menor = min(largura, altura)
        maior = max(largura, altura)

        if largura < LARGURA_MIN_PX or altura < ALTURA_MIN_PX:
            log.warning(
                f"Imagem não encontrada/descartada em {url}: "
                f"dimensões {largura}x{altura}, mínimo {LARGURA_MIN_PX}x{ALTURA_MIN_PX}."
            )
            return None

        if menor and maior / menor > PROPORCAO_MAX:
            log.warning(
                f"Imagem não encontrada/descartada em {url}: "
                f"proporção {maior / menor:.2f}, máximo {PROPORCAO_MAX}."
            )
            return None

        log.info(
            f"OK - Download da imagem concluído: {url} "
            f"({largura}x{altura}, {len(conteudo) // 1024} KB)."
        )
        return img

    except Exception as e:
        log.warning(f"Erro ao baixar imagem em {url}: {e}", exc_info=True)
        return None
