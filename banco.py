import logging
import re
from typing import Optional

from config import (
    COLUNA_CODIGO_OFERTA,
    COLUNA_DESCRICAO_OFERTA,
    DB_CLIENT_LIB_DIR,
    DB_CONNECT_TIMEOUT,
    DB_DSN,
    DB_PASSWORD,
    DB_PROVIDER,
    DB_USER,
    ODBC_CONNECTION_STRING,
    PRODUTOS_POR_LOTE,
    TABELA_OFERTAS,
)


log = logging.getLogger(__name__)


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


def montar_sql_base_produtos() -> str:
    """Monta a base do SELECT das ofertas ativas."""
    tabela_ofertas = validar_identificador_sql(TABELA_OFERTAS, "TABELA_OFERTAS")
    coluna_codigo_oferta = validar_identificador_sql(COLUNA_CODIGO_OFERTA, "COLUNA_CODIGO_OFERTA")
    coluna_descricao_oferta = validar_identificador_sql(
        COLUNA_DESCRICAO_OFERTA,
        "COLUNA_DESCRICAO_OFERTA",
    )
    return f"""
        SELECT DISTINCT
               o.{coluna_codigo_oferta} AS procodbase,
               o.{coluna_descricao_oferta} AS prodescricao
          FROM {tabela_ofertas} o
         WHERE o.{coluna_codigo_oferta} IS NOT NULL
           AND o.{coluna_descricao_oferta} IS NOT NULL
    """


def montar_sql_produtos() -> str:
    """Monta o SELECT completo das ofertas ativas."""
    return f"""
        {montar_sql_base_produtos()}
         ORDER BY prodescricao, procodbase
    """


def montar_sql_lote_produtos() -> str:
    """Monta o SELECT paginado por chave para buscar produtos em lotes."""
    return f"""
        SELECT procodbase, prodescricao
          FROM (
            SELECT procodbase, prodescricao
              FROM (
                {montar_sql_base_produtos()}
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
    Busca um lote de ofertas ativas no Oracle.
    Retorna tuplas (prodescricao_para_buscar, procodbase_para_nomear_arquivo).
    """
    sql = montar_sql_lote_produtos()
    parametros = {
        "ultima_descricao": ultimo_produto[0] if ultimo_produto else None,
        "ultimo_codigo": ultimo_produto[1] if ultimo_produto else None,
        "limite_lote": tamanho_lote,
    }
    log.info(
        "Buscando ofertas ativas no banco "
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
            log.info(f"Resultado da busca no banco: {len(produtos)} oferta(s) ativa(s).")
            for nome_busca, nome_arquivo in produtos:
                log.info(f"Produto retornado pelo banco: '{nome_busca}' (PROCODBASE={nome_arquivo})")
            return produtos
        except Exception as e:
            log.warning(f"Erro ao buscar ofertas ativas no banco: {e}", exc_info=True)
            raise
        finally:
            cursor.close()
    finally:
        conexao.close()
        log.info("Conexão da busca de produtos fechada.")


def iterar_lotes_produtos_banco(tamanho_lote: int):
    """
    Busca ofertas ativas em lotes, sem manter a lista completa em memoria.
    No Oracle, cada lote usa uma consulta limitada; em outros provedores,
    usa fetchmany para não carregar todos os registros no Python de uma vez.
    """
    log.info(f"Consultando ofertas ativas em lotes de até {tamanho_lote} produtos...")

    if DB_PROVIDER == "oracle":
        ultimo_produto = None

        while True:
            produtos = ler_lote_produtos_banco(ultimo_produto, tamanho_lote)

            if not produtos:
                log.info("Nenhuma nova oferta ativa encontrada no banco.")
                break

            yield produtos
            ultimo_produto = produtos[-1]

        return

    sql = montar_sql_produtos()
    try:
        conexao = conectar_banco()
    except Exception as e:
        log.warning(f"Erro ao conectar ao banco para buscar produtos: {e}", exc_info=True)
        raise

    try:
        cursor = conexao.cursor()
        cursor.arraysize = tamanho_lote
        try:
            log.info("Executando consulta de ofertas ativas no banco.")
            cursor.execute(sql)

            while True:
                linhas = cursor.fetchmany(tamanho_lote)

                if not linhas:
                    log.info("Nenhuma nova oferta ativa encontrada no banco.")
                    break

                produtos = normalizar_linhas_produtos(linhas)
                log.info(f"Resultado da busca no banco: {len(produtos)} oferta(s) ativa(s).")
                for nome_busca, nome_arquivo in produtos:
                    log.info(f"Produto retornado pelo banco: '{nome_busca}' (PROCODBASE={nome_arquivo})")

                if produtos:
                    yield produtos
        except Exception as e:
            log.warning(f"Erro ao buscar ofertas ativas no banco: {e}", exc_info=True)
            raise
        finally:
            cursor.close()
    finally:
        conexao.close()
        log.info("Conexão da busca de produtos fechada.")


def ler_produtos_banco() -> list[tuple[str, str]]:
    """
    Busca no banco as ofertas ativas.
    Mantida para compatibilidade; o fluxo principal usa lotes.
    """
    produtos = []

    for lote in iterar_lotes_produtos_banco(PRODUTOS_POR_LOTE):
        produtos.extend(lote)

    return produtos
