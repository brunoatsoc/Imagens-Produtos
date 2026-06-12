import logging
import random
import re
import time

from tqdm import tqdm

from banco import iterar_lotes_produtos_banco
from busca_imagens import (
    baixar_imagem,
    buscar_candidatos_imagens,
    resumir_candidato,
)
from config import (
    ALTURA_FINAL_PX,
    DELAY_MAX,
    DELAY_MIN,
    LARGURA_FINAL_PX,
    PASTA_SAIDA,
    PRODUTOS_POR_LOTE,
    resolver_pasta_saida,
)
from processamento_imagens import (
    ajustar_imagem_existente,
    redimensionar_para_tamanho_final,
)


log = logging.getLogger(__name__)


def sanitizar_nome(nome: str) -> str:
    """Remove caracteres inválidos para nome de arquivo."""
    caracteres_invalidos = r'\/:*?"<>|'
    for c in caracteres_invalidos:
        nome = nome.replace(c, "_")
    return nome.strip()[:100]


def main():
    pasta = resolver_pasta_saida(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)
    tamanho_final = f"{LARGURA_FINAL_PX}x{ALTURA_FINAL_PX}"

    log.info(f"As imagens serão salvas em PNG com fundo original no tamanho {tamanho_final}.")
    log.info(f"Pasta de saída das imagens: {pasta.resolve()}")

    sucesso    = 0
    falha      = 0
    ja_existia = 0
    redimensionadas = 0
    total_produtos = 0

    for numero_lote, produtos in enumerate(iterar_lotes_produtos_banco(PRODUTOS_POR_LOTE), start=1):
        total_produtos += len(produtos)

        log.info(f"Lote {numero_lote}: {len(produtos)} ofertas ativas sem imagem encontradas no banco.")

        for nome_busca, nome_arquivo in tqdm(produtos, desc=f"Baixando lote {numero_lote}", unit="produto"):
            # Salva sempre como .png para manter o formato esperado pelo fluxo atual.
            nome_final = sanitizar_nome(nome_arquivo)
            nome_final = re.sub(r'\.(jpg|jpeg|png|webp)$', '', nome_final, flags=re.IGNORECASE)
            nome_final += ".png"

            caminho_img = pasta / nome_final
            log.info(
                f"Produto em busca: '{nome_busca}' "
                f"(PROCODBASE={nome_arquivo}, arquivo esperado={nome_final})"
            )

            # Pula se já foi baixada
            if caminho_img.exists():
                log.info(f"OK - Imagem já existe em disco para '{nome_busca}': {caminho_img}")
                if ajustar_imagem_existente(caminho_img):
                    redimensionadas += 1
                    log.info(f"Imagem ajustada para {tamanho_final}: {nome_final}")

                ja_existia += 1
                continue

            candidatos = buscar_candidatos_imagens(nome_busca)
            log.info(
                f"Resultado da busca para '{nome_busca}': "
                f"{len(candidatos)} candidato(s) confiável(is) encontrado(s)."
            )

            baixou = False
            for candidato in candidatos:
                log.info(
                    f"Tentando baixar imagem para '{nome_busca}': "
                    f"{resumir_candidato(candidato)} url={candidato.url}"
                )
                img = baixar_imagem(candidato.url)
                if img is None:
                    log.warning(
                        f"Imagem não encontrada para '{nome_busca}' neste candidato: "
                        f"{resumir_candidato(candidato)}"
                    )
                    continue

                try:
                    log.info(
                        f"Redimensionando imagem: '{nome_busca}' "
                        f"({resumir_candidato(candidato)})..."
                    )
                    img_final = redimensionar_para_tamanho_final(img)
                    img_final.save(caminho_img, "PNG")
                    log.info(f"OK - Imagem baixada e salva para '{nome_busca}': {caminho_img}")
                    log.info(f"'{nome_busca}' → {nome_final}")
                    sucesso += 1
                    baixou = True
                    break
                except Exception as e:
                    log.warning(
                        f"Erro ao processar/salvar imagem de '{nome_busca}' "
                        f"(arquivo esperado: {nome_final}): {e}",
                        exc_info=True,
                    )
                    continue

            if not baixou:
                log.warning(f"Imagem não encontrada para '{nome_busca}' (arquivo esperado: {nome_final})")
                log.warning(f"Sem imagem para: '{nome_busca}' (arquivo esperado: {nome_final})")
                falha += 1

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    log.info("=" * 50)
    log.info(f" CONCLUÍDO!")
    log.info(f"    Produtos processados: {total_produtos}")
    log.info(f"    Baixados com sucesso : {sucesso}")
    log.info(f"    Já existiam         : {ja_existia}")
    log.info(f"    Ajustadas {tamanho_final}   : {redimensionadas}")
    log.info(f"    Falhas               : {falha}")
    log.info(f"    Pendentes locais     : {sucesso + ja_existia}")
    log.info(f"    Imagens locais em    : {pasta.resolve()}")
    log.info("    Nenhuma imagem foi salva automaticamente no banco.")
    log.info("    Use a tela de gerenciamento para selecionar e persistir as imagens desejadas.")
    log.info("    Para abrir a tela: python teste.py gerenciar")
    log.info("=" * 50)
