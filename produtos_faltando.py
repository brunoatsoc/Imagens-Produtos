"""
Gera um CSV com os produtos que ainda nao possuem imagem baixada.

Como usar:
    python produtos_faltando.py

O script compara o arquivo produtos.csv com os arquivos existentes na pasta
imagens_produtos e cria produtos_faltando.csv com as mesmas colunas do CSV
original, pronto para ser usado depois no download das imagens pendentes.
"""

import csv
import re
from pathlib import Path


CSV_FILE = "produtos.csv"
PASTA_IMAGENS = "imagens_produtos"
CSV_SAIDA = "produtos_faltando.csv"

COLUNA_BUSCA = "nome_produto"
COLUNA_ARQUIVO = "nome_imagem"

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "latin1")
EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}


def sanitizar_nome(nome: str) -> str:
    """Repete a regra usada pelo teste.py para montar o nome esperado."""
    caracteres_invalidos = r'\/:*?"<>|'
    for c in caracteres_invalidos:
        nome = nome.replace(c, "_")
    return nome.strip()[:100]


def detectar_delimitador(caminho: Path, encoding: str) -> str:
    with caminho.open("r", encoding=encoding, newline="") as arquivo:
        primeira_linha = arquivo.readline()
    return ";" if ";" in primeira_linha else ","


def ler_csv(caminho: str) -> tuple[list[dict], list[str], str]:
    caminho_csv = Path(caminho)

    for encoding in CSV_ENCODINGS:
        try:
            delimitador = detectar_delimitador(caminho_csv, encoding)
            with caminho_csv.open("r", encoding=encoding, newline="") as arquivo:
                reader = csv.DictReader(arquivo, delimiter=delimitador)
                linhas = [
                    {chave: (valor or "").strip() for chave, valor in linha.items()}
                    for linha in reader
                ]
                return linhas, list(reader.fieldnames or []), encoding
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Nao foi possivel ler {caminho} com: {', '.join(CSV_ENCODINGS)}")


def nome_imagem_esperado(linha: dict) -> str:
    nome_busca = linha.get(COLUNA_BUSCA, "").strip()
    nome_arquivo = linha.get(COLUNA_ARQUIVO, "").strip() or nome_busca
    nome_final = sanitizar_nome(nome_arquivo)
    nome_final = re.sub(r"\.(jpg|jpeg|png|webp)$", "", nome_final, flags=re.IGNORECASE)
    return f"{nome_final}.png"


def imagens_existentes(pasta: str) -> tuple[set[str], set[str]]:
    caminho_pasta = Path(pasta)

    if not caminho_pasta.exists():
        return set(), set()

    nomes = set()
    nomes_sem_extensao = set()

    for arquivo in caminho_pasta.iterdir():
        if not arquivo.is_file():
            continue

        if arquivo.suffix.lower() not in EXTENSOES_IMAGEM:
            continue

        nomes.add(arquivo.name.casefold())
        nomes_sem_extensao.add(arquivo.stem.casefold())

    return nomes, nomes_sem_extensao


def produto_tem_imagem(nome_esperado: str, nomes: set[str], nomes_sem_extensao: set[str]) -> bool:
    caminho_esperado = Path(nome_esperado)
    return (
        caminho_esperado.name.casefold() in nomes
        or caminho_esperado.stem.casefold() in nomes_sem_extensao
    )


def salvar_csv(caminho: str, linhas: list[dict], colunas: list[str]) -> None:
    with Path(caminho).open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writeheader()
        writer.writerows(linhas)


def main() -> None:
    produtos, colunas, encoding_usado = ler_csv(CSV_FILE)

    if COLUNA_BUSCA not in colunas or COLUNA_ARQUIVO not in colunas:
        raise ValueError(
            f"O CSV precisa ter as colunas '{COLUNA_BUSCA}' e '{COLUNA_ARQUIVO}'."
        )

    nomes, nomes_sem_extensao = imagens_existentes(PASTA_IMAGENS)

    faltando = []
    for linha in produtos:
        esperado = nome_imagem_esperado(linha)
        if not produto_tem_imagem(esperado, nomes, nomes_sem_extensao):
            faltando.append(linha)

    salvar_csv(CSV_SAIDA, faltando, colunas)

    print(f"CSV lido: {CSV_FILE} ({encoding_usado})")
    print(f"Produtos no CSV: {len(produtos)}")
    print(f"Imagens encontradas: {len(nomes)}")
    print(f"Produtos faltando imagem: {len(faltando)}")
    print(f"Arquivo gerado: {CSV_SAIDA}")


if __name__ == "__main__":
    main()
