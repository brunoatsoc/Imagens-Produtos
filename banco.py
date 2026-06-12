import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from config import (
    COLUNA_CODIGO_IMAGEM,
    COLUNA_CODIGO_OFERTA,
    COLUNA_DESCRICAO_OFERTA,
    DB_CLIENT_LIB_DIR,
    DB_CONNECT_TIMEOUT,
    DB_DSN,
    DB_PASSWORD,
    DB_PROVIDER,
    DB_USER,
    FLAG_EVTCOM_AUTOMATICO,
    ODBC_CONNECTION_STRING,
    PRODUTOS_POR_LOTE,
    TABELA_IMAGENS,
    TABELA_OFERTAS,
    USUARIO_ALTERACAO_IMAGEM,
)


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultadoPersistenciaImagem:
    codigo: int
    caminho: Path
    inserida: bool = False
    ja_existia: bool = False
    erro: str = ""

    @property
    def sucesso(self) -> bool:
        return self.inserida or self.ja_existia

    @property
    def status(self) -> str:
        if self.inserida:
            return "inserida"
        if self.ja_existia:
            return "ja_existia"
        return "falha"


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

        log.info(f"Conectando ao banco Oracle: dsn={DB_DSN}")
        conexao = oracledb.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            dsn=DB_DSN,
        )
        log.info("OK - Conexão com banco Oracle aberta.")
        return conexao

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

        log.info("Conectando ao banco via ODBC.")
        conexao = pyodbc.connect(ODBC_CONNECTION_STRING, timeout=DB_CONNECT_TIMEOUT)
        log.info("OK - Conexão com banco via ODBC aberta.")
        return conexao

    raise ValueError("DB_PROVIDER deve ser 'oracle' ou 'odbc'")


def normalizar_linhas_produtos(linhas) -> list[tuple[str, str]]:
    produtos = []

    for procodbase, prodescricao in linhas:
        nome_busca = str(prodescricao or "").strip()
        nome_arquivo = str(procodbase or "").strip()

        if not nome_busca or not nome_arquivo:
            log.warning(
                f"Produto ignorado na leitura do banco: "
                f"procodbase={procodbase!r}, prodescricao={prodescricao!r}"
            )
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
    log.info(
        "Buscando produtos sem imagem no banco "
        f"(limite={tamanho_lote}, ultimo_produto={ultimo_produto})."
    )

    try:
        conexao = conectar_banco()
    except Exception as e:
        log.warning(f"Erro ao conectar ao banco para buscar produtos: {e}", exc_info=True)
        raise

    try:
        cursor = conexao.cursor()
        cursor.arraysize = tamanho_lote
        try:
            cursor.execute(sql, parametros)
            produtos = normalizar_linhas_produtos(cursor)
            log.info(f"Resultado da busca no banco: {len(produtos)} produto(s) sem imagem.")
            for nome_busca, nome_arquivo in produtos:
                log.info(f"Produto retornado pelo banco: '{nome_busca}' (PROCODBASE={nome_arquivo})")
            return produtos
        except Exception as e:
            log.warning(f"Erro ao buscar produtos sem imagem no banco: {e}", exc_info=True)
            raise
        finally:
            cursor.close()
    finally:
        conexao.close()
        log.info("Conexão da busca de produtos fechada.")


def iterar_lotes_produtos_banco(tamanho_lote: int):
    """
    Busca produtos sem imagem em lotes, sem manter a lista completa em memoria.
    No Oracle, cada lote usa uma consulta limitada; em outros provedores,
    usa fetchmany para não carregar todos os registros no Python de uma vez.
    """
    log.info(f"Consultando ofertas ativas sem imagem em lotes de até {tamanho_lote} produtos...")

    if DB_PROVIDER == "oracle":
        ultimo_produto = None

        while True:
            produtos = ler_lote_produtos_banco(ultimo_produto, tamanho_lote)

            if not produtos:
                log.info("Nenhum novo produto sem imagem encontrado no banco.")
                break

            yield produtos
            ultimo_produto = produtos[-1]

        return

    sql = montar_sql_produtos_sem_imagem()
    try:
        conexao = conectar_banco()
    except Exception as e:
        log.warning(f"Erro ao conectar ao banco para buscar produtos: {e}", exc_info=True)
        raise

    try:
        cursor = conexao.cursor()
        cursor.arraysize = tamanho_lote
        try:
            log.info("Executando consulta de produtos sem imagem no banco.")
            cursor.execute(sql)

            while True:
                linhas = cursor.fetchmany(tamanho_lote)

                if not linhas:
                    log.info("Nenhum novo produto sem imagem encontrado no banco.")
                    break

                produtos = normalizar_linhas_produtos(linhas)
                log.info(f"Resultado da busca no banco: {len(produtos)} produto(s) sem imagem.")
                for nome_busca, nome_arquivo in produtos:
                    log.info(f"Produto retornado pelo banco: '{nome_busca}' (PROCODBASE={nome_arquivo})")

                if produtos:
                    yield produtos
        except Exception as e:
            log.warning(f"Erro ao buscar produtos sem imagem no banco: {e}", exc_info=True)
            raise
        finally:
            cursor.close()
    finally:
        conexao.close()
        log.info("Conexão da busca de produtos fechada.")


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


def montar_sql_verificar_imagem() -> str:
    """Monta o SELECT que verifica se um código já possui imagem no banco."""
    tabela_imagens = validar_identificador_sql(TABELA_IMAGENS, "TABELA_IMAGENS")
    coluna_codigo_imagem = validar_identificador_sql(COLUNA_CODIGO_IMAGEM, "COLUNA_CODIGO_IMAGEM")

    return f"""
        SELECT 1
          FROM {tabela_imagens}
         WHERE {coluna_codigo_imagem} = :codigo
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


def executar_insert_imagem(cursor, codigo: int, caminho_img: Path, sql: Optional[str] = None) -> None:
    """Executa o INSERT de uma única imagem usando o cursor já aberto."""
    if not caminho_img.exists():
        raise FileNotFoundError(f"arquivo local não encontrado: {caminho_img}")

    sql = sql or montar_sql_insert_imagem()
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


def persistir_imagens_banco(imagens_prontas: dict[int, Path]) -> list[ResultadoPersistenciaImagem]:
    """
    Persiste imagens selecionadas no banco e retorna o resultado individual.
    O retorno só acontece depois do commit, para permitir remoção local segura.
    """
    if not imagens_prontas:
        log.info("Nenhuma imagem selecionada para salvar no banco.")
        return []

    sql = montar_sql_insert_imagem()
    resultados: list[ResultadoPersistenciaImagem] = []
    houve_insert = False

    log.info(f"Persistindo {len(imagens_prontas)} imagem(ns) selecionada(s) em {TABELA_IMAGENS}.")

    try:
        conexao = conectar_banco()
    except Exception as e:
        log.warning(f"Erro ao conectar ao banco para salvar imagens: {e}", exc_info=True)
        raise

    try:
        cursor = conexao.cursor()
        try:
            configurar_bind_blob(cursor)

            for codigo, caminho_img in imagens_prontas.items():
                try:
                    log.info(f"Salvando imagem selecionada: {caminho_img.name} (PROCODBASE={codigo})")
                    executar_insert_imagem(cursor, codigo, caminho_img, sql=sql)
                    resultados.append(
                        ResultadoPersistenciaImagem(
                            codigo=codigo,
                            caminho=caminho_img,
                            inserida=True,
                        )
                    )
                    houve_insert = True
                    log.info(f"OK - Imagem preparada para commit: {caminho_img.name} (PROCODBASE={codigo})")
                except Exception as e:
                    if erro_chave_duplicada(e):
                        resultados.append(
                            ResultadoPersistenciaImagem(
                                codigo=codigo,
                                caminho=caminho_img,
                                ja_existia=True,
                            )
                        )
                        log.info(
                            f"Imagem já estava persistida no banco: "
                            f"{caminho_img.name} (PROCODBASE={codigo})"
                        )
                        continue

                    resultados.append(
                        ResultadoPersistenciaImagem(
                            codigo=codigo,
                            caminho=caminho_img,
                            erro=str(e),
                        )
                    )
                    log.warning(
                        f"Falha ao salvar imagem selecionada '{caminho_img.name}' "
                        f"(PROCODBASE={codigo}): {e}",
                        exc_info=True,
                    )

            if houve_insert:
                conexao.commit()
                log.info("OK - Commit das imagens selecionadas concluído.")
            else:
                log.info("Nenhum novo registro foi inserido; commit não necessário.")
        finally:
            cursor.close()
    except Exception as e:
        log.warning(f"Erro geral ao persistir imagens selecionadas: {e}", exc_info=True)
        conexao.rollback()
        raise
    finally:
        conexao.close()
        log.info("Conexão de persistência manual de imagens fechada.")

    return resultados


def imagem_existe_banco(codigo: str | int, conexao=None) -> bool:
    """Verifica se o código informado já possui imagem persistida no banco."""
    codigo_banco = preparar_codigo_banco(str(codigo))
    sql = montar_sql_verificar_imagem()
    conexao_local = conexao is None

    if conexao_local:
        conexao = conectar_banco()

    try:
        cursor = conexao.cursor()
        try:
            cursor.execute(sql, {"codigo": codigo_banco})
            return cursor.fetchone() is not None
        finally:
            cursor.close()
    finally:
        if conexao_local:
            conexao.close()


def listar_codigos_imagens_existentes(codigos: Iterable[str | int]) -> set[int]:
    """
    Retorna os códigos que já possuem imagem no banco.
    Usa uma única conexão e consultas simples para manter compatibilidade
    com os provedores já suportados pelo projeto.
    """
    codigos_validos = []

    for codigo in codigos:
        try:
            codigo_banco = preparar_codigo_banco(str(codigo))
        except ValueError as e:
            log.warning(f"{e}. Código ignorado na verificação de pendências.")
            continue

        if codigo_banco not in codigos_validos:
            codigos_validos.append(codigo_banco)

    if not codigos_validos:
        return set()

    existentes = set()
    log.info(f"Verificando {len(codigos_validos)} código(s) de imagem já existente(s) no banco.")

    try:
        conexao = conectar_banco()
    except Exception as e:
        log.warning(f"Erro ao conectar ao banco para verificar imagens existentes: {e}", exc_info=True)
        raise

    try:
        for codigo in codigos_validos:
            try:
                if imagem_existe_banco(codigo, conexao=conexao):
                    existentes.add(codigo)
            except Exception as e:
                log.warning(
                    f"Erro ao verificar imagem existente no banco "
                    f"(PROCODBASE={codigo}): {e}",
                    exc_info=True,
                )
                raise
    finally:
        conexao.close()
        log.info("Conexão de verificação de imagens fechada.")

    return existentes


def registrar_imagem_pronta(
    imagens_prontas: dict[int, Path],
    codigo: str,
    caminho_img: Path,
) -> None:
    """Guarda uma imagem pronta para ser inserida no banco ao final."""
    if not caminho_img.exists():
        log.warning(
            f"Imagem não encontrada em disco para salvar no banco "
            f"(PROCODBASE={codigo}): {caminho_img}"
        )
        return

    try:
        codigo_banco = preparar_codigo_banco(codigo)
        imagens_prontas[codigo_banco] = caminho_img
        log.info(f"OK - Imagem pronta para salvar no banco: {caminho_img.name} (PROCODBASE={codigo_banco})")
    except ValueError as e:
        log.warning(f"{e}. Arquivo ignorado no insert: {caminho_img.name}")


def inserir_imagens_banco(imagens_prontas: dict[int, Path]) -> tuple[int, int, int]:
    """
    Insere no banco as imagens geradas/localizadas.
    Retorna (inseridas, ja_existiam_no_banco, falhas).
    """
    resultados = persistir_imagens_banco(imagens_prontas)
    inseridas = sum(1 for resultado in resultados if resultado.inserida)
    ja_existiam = sum(1 for resultado in resultados if resultado.ja_existia)
    falhas = sum(1 for resultado in resultados if not resultado.sucesso)
    return inseridas, ja_existiam, falhas
