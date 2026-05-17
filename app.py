import logging
import random
import re
import time
from pathlib import Path

from tqdm import tqdm

from banco import inserir_imagens_banco, iterar_lotes_produtos_banco, registrar_imagem_pronta
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
    remover_fundo,
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
