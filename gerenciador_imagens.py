import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from banco import (
    ResultadoPersistenciaImagem,
    listar_codigos_imagens_existentes,
    persistir_imagens_banco,
    preparar_codigo_banco,
)
from config import PASTA_SAIDA, resolver_pasta_saida


log = logging.getLogger(__name__)

EXTENSOES_IMAGENS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ImagemLocal:
    codigo: int
    nome_arquivo: str
    caminho: Path
    tamanho_bytes: int
    atualizado_em: float


@dataclass(frozen=True)
class ResultadoRemocaoLocal:
    nome_arquivo: str
    removida: bool
    erro: str = ""


@dataclass(frozen=True)
class ResultadoGerenciamento:
    persistencias: list[ResultadoPersistenciaImagem]
    remocoes: list[ResultadoRemocaoLocal]
    erros: list[str]

    @property
    def inseridas(self) -> int:
        return sum(1 for resultado in self.persistencias if resultado.inserida)

    @property
    def ja_existiam(self) -> int:
        return sum(1 for resultado in self.persistencias if resultado.ja_existia)

    @property
    def falhas_persistencia(self) -> int:
        return sum(1 for resultado in self.persistencias if not resultado.sucesso)

    @property
    def removidas(self) -> int:
        return sum(1 for resultado in self.remocoes if resultado.removida)

    @property
    def falhas_remocao(self) -> int:
        return sum(1 for resultado in self.remocoes if not resultado.removida)


def obter_pasta_local() -> Path:
    """Retorna a pasta local usada como armazenamento temporário."""
    pasta = resolver_pasta_saida(PASTA_SAIDA)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_esta_na_pasta(caminho: Path, pasta: Path) -> bool:
    try:
        caminho.resolve().relative_to(pasta.resolve())
        return True
    except ValueError:
        return False


def codigo_por_nome_arquivo(nome_arquivo: str) -> int:
    """Extrai o PROCODBASE do nome local esperado: {PROCODBASE}.png."""
    return preparar_codigo_banco(Path(nome_arquivo).stem)


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
    """Lista arquivos locais com nome compatível com o código do banco."""
    pasta = obter_pasta_local()
    imagens: list[ImagemLocal] = []

    for caminho in sorted(pasta.iterdir(), key=lambda item: item.name.lower()):
        if not caminho.is_file() or caminho.suffix.lower() not in EXTENSOES_IMAGENS:
            continue

        try:
            codigo = codigo_por_nome_arquivo(caminho.name)
        except ValueError as e:
            log.warning(f"{e}. Arquivo local ignorado na galeria: {caminho.name}")
            continue

        try:
            stat = caminho.stat()
        except OSError as e:
            log.warning(f"Não foi possível ler metadados do arquivo local '{caminho.name}': {e}")
            continue

        imagens.append(
            ImagemLocal(
                codigo=codigo,
                nome_arquivo=caminho.name,
                caminho=caminho,
                tamanho_bytes=stat.st_size,
                atualizado_em=stat.st_mtime,
            )
        )

    return imagens


def listar_imagens_pendentes() -> list[ImagemLocal]:
    """
    Lista imagens locais que ainda não foram persistidas no banco.
    Se a verificação no banco falhar, a exceção é propagada para a tela.
    """
    imagens = listar_arquivos_locais()

    if not imagens:
        return []

    codigos_existentes = listar_codigos_imagens_existentes(imagem.codigo for imagem in imagens)
    pendentes = [imagem for imagem in imagens if imagem.codigo not in codigos_existentes]
    log.info(
        f"Galeria local: {len(imagens)} arquivo(s) válido(s), "
        f"{len(pendentes)} pendente(s), {len(codigos_existentes)} já persistido(s)."
    )
    return pendentes


def preparar_imagens_selecionadas(nomes_arquivos: Iterable[str]) -> tuple[dict[int, Path], list[str]]:
    imagens: dict[int, Path] = {}
    erros: list[str] = []

    for nome_arquivo in nomes_arquivos:
        try:
            caminho = arquivo_local_por_nome(nome_arquivo)
            codigo = codigo_por_nome_arquivo(caminho.name)
        except Exception as e:
            erro = f"{nome_arquivo}: {e}"
            erros.append(erro)
            log.warning(f"Imagem selecionada ignorada: {erro}", exc_info=True)
            continue

        if codigo in imagens:
            erro = f"{nome_arquivo}: código duplicado na seleção ({codigo})"
            erros.append(erro)
            log.warning(erro)
            continue

        imagens[codigo] = caminho

    return imagens, erros


def remover_arquivos_persistidos(
    resultados: Iterable[ResultadoPersistenciaImagem],
) -> list[ResultadoRemocaoLocal]:
    remocoes: list[ResultadoRemocaoLocal] = []

    for resultado in resultados:
        if not resultado.sucesso:
            continue

        try:
            resultado.caminho.unlink()
            remocoes.append(
                ResultadoRemocaoLocal(
                    nome_arquivo=resultado.caminho.name,
                    removida=True,
                )
            )
            log.info(f"OK - Arquivo local removido após persistência: {resultado.caminho.name}")
        except FileNotFoundError:
            remocoes.append(
                ResultadoRemocaoLocal(
                    nome_arquivo=resultado.caminho.name,
                    removida=True,
                )
            )
            log.info(f"Arquivo local já não existia após persistência: {resultado.caminho.name}")
        except Exception as e:
            remocoes.append(
                ResultadoRemocaoLocal(
                    nome_arquivo=resultado.caminho.name,
                    removida=False,
                    erro=str(e),
                )
            )
            log.warning(
                f"Imagem persistida, mas não foi possível remover o arquivo local "
                f"'{resultado.caminho.name}': {e}",
                exc_info=True,
            )

    return remocoes


def salvar_imagens_selecionadas(nomes_arquivos: Iterable[str]) -> ResultadoGerenciamento:
    """
    Salva imagens selecionadas no banco e remove os arquivos locais só após commit.
    Imagens com falha de persistência permanecem na pasta local.
    """
    imagens, erros = preparar_imagens_selecionadas(nomes_arquivos)

    if not imagens:
        return ResultadoGerenciamento(persistencias=[], remocoes=[], erros=erros)

    resultados = persistir_imagens_banco(imagens)
    remocoes = remover_arquivos_persistidos(resultados)
    return ResultadoGerenciamento(persistencias=resultados, remocoes=remocoes, erros=erros)


def excluir_imagens_locais(nomes_arquivos: Iterable[str]) -> list[ResultadoRemocaoLocal]:
    """Remove arquivos locais indesejados sem tocar no banco."""
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
