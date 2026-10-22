import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config import PASTA_SAIDA, resolver_pasta_saida


log = logging.getLogger(__name__)

EXTENSOES_IMAGENS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ImagemLocal:
    codigo: str
    nome_arquivo: str
    caminho: Path
    tamanho_bytes: int
    atualizado_em: float


@dataclass(frozen=True)
class ResultadoRemocaoLocal:
    nome_arquivo: str
    removida: bool
    erro: str = ""


def obter_pasta_local() -> Path:
    """Retorna a pasta configurada para armazenar as imagens baixadas."""
    pasta = resolver_pasta_saida(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_esta_na_pasta(caminho: Path, pasta: Path) -> bool:
    try:
        caminho.resolve().relative_to(pasta.resolve())
        return True
    except ValueError:
        return False


def arquivo_local_por_nome(nome_arquivo: str) -> Path:
    """Resolve e valida um arquivo local informado pela interface."""
    pasta = obter_pasta_local()
    nome_original = str(nome_arquivo or "")
    nome = Path(nome_original).name

    if not nome or nome != nome_original or "/" in nome or "\\" in nome:
        raise ValueError(f"nome de arquivo inválido: {nome_arquivo!r}")

    caminho = pasta / nome
    if caminho.suffix.lower() not in EXTENSOES_IMAGENS:
        raise ValueError(f"extensão de imagem não suportada: {nome}")
    if not caminho_esta_na_pasta(caminho, pasta):
        raise ValueError(f"arquivo fora da pasta local: {nome}")
    if not caminho.is_file():
        raise FileNotFoundError(f"arquivo local não encontrado: {nome}")

    return caminho


def listar_arquivos_locais() -> list[ImagemLocal]:
    """Lista todas as imagens existentes na pasta de saída."""
    pasta = obter_pasta_local()
    imagens: list[ImagemLocal] = []

    for caminho in sorted(pasta.iterdir(), key=lambda item: item.name.lower()):
        if not caminho.is_file() or caminho.suffix.lower() not in EXTENSOES_IMAGENS:
            continue
        try:
            stat = caminho.stat()
        except OSError as e:
            log.warning(f"Não foi possível ler metadados do arquivo local '{caminho.name}': {e}")
            continue
        imagens.append(
            ImagemLocal(
                codigo=caminho.stem,
                nome_arquivo=caminho.name,
                caminho=caminho,
                tamanho_bytes=stat.st_size,
                atualizado_em=stat.st_mtime,
            )
        )
    return imagens


def excluir_imagens_locais(nomes_arquivos: Iterable[str]) -> list[ResultadoRemocaoLocal]:
    """Remove fisicamente arquivos locais selecionados."""
    resultados: list[ResultadoRemocaoLocal] = []
    for nome_arquivo in nomes_arquivos:
        try:
            caminho = arquivo_local_por_nome(nome_arquivo)
            caminho.unlink()
            resultados.append(ResultadoRemocaoLocal(nome_arquivo=caminho.name, removida=True))
            log.info(f"OK - Arquivo local excluído pelo usuário: {caminho.name}")
        except Exception as e:
            nome = Path(str(nome_arquivo or "")).name or str(nome_arquivo)
            resultados.append(ResultadoRemocaoLocal(nome_arquivo=nome, removida=False, erro=str(e)))
            log.warning(f"Erro ao excluir arquivo local '{nome_arquivo}': {e}", exc_info=True)
    return resultados
