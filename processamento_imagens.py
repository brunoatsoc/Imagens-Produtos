import logging
from pathlib import Path

from PIL import Image

from config import ALTURA_FINAL_PX, LARGURA_FINAL_PX, MARGEM_FINAL_PX


log = logging.getLogger(__name__)


def redimensionar_para_tamanho_final(img: Image.Image) -> Image.Image:
    """Centraliza a imagem no tamanho final configurado, sem deformar."""
    img = img.convert("RGBA")
    largura_final = LARGURA_FINAL_PX
    altura_final = ALTURA_FINAL_PX
    margem = max(0, MARGEM_FINAL_PX)

    alpha = img.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > 15 else 0)
    bbox = mask.getbbox()
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
