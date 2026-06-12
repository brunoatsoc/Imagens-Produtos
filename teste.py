"""
=============================================================
  Script: Buscador de Imagens de Produtos para Mercado
=============================================================
  Como usar:
  1. Instale as dependências:
       pip install requests pillow tqdm ddgs oracledb

  2. Configure o acesso ao banco no arquivo .env, na mesma pasta do script:
       DB_PROVIDER=oracle
       DB_USER=usuario
       DB_PASSWORD=senha
       DB_DSN=host:porta/servico
       TABELA_OFERTAS=CLIENTE.WSOFERTASATIVAS
       TABELA_IMAGENS=CLIENTE.PRODUTOSIMAGENS
       LARGURA_FINAL_PX=406
       ALTURA_FINAL_PX=406

     Por padrão o script usa Oracle via python-oracledb.
     Para usar ODBC, configure:
       DB_PROVIDER=odbc
       ODBC_CONNECTION_STRING=DSN=meu_dsn;UID=usuario;PWD=senha

  3. Execute:
       python teste.py baixar

     Para abrir a tela de gerenciamento das imagens locais:
       python teste.py gerenciar

  4. Para rodar o script no WSL2
        Primeiro crie o ambiente dentro do linux
            python3 -m venv venv
            source venv/bin/activate
        Depois rode os comandos de instalação dos pacotes normalmente
            pip install requests pillow tqdm ddgs oracledb

ATENÇÃO: As imagens serão salvas em PNG com o fundo original preservado.
=============================================================
"""

import argparse


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Busca imagens de produtos e gerencia a persistência manual no banco.",
    )
    subparsers = parser.add_subparsers(dest="comando")

    subparsers.add_parser(
        "baixar",
        help="Busca e baixa imagens localmente, sem salvar automaticamente no banco.",
    )

    parser_gerenciar = subparsers.add_parser(
        "gerenciar",
        help="Abre a tela local para selecionar, salvar ou excluir imagens baixadas.",
    )
    parser_gerenciar.add_argument("--host", default="127.0.0.1", help="Host da tela local.")
    parser_gerenciar.add_argument(
        "--porta",
        type=int,
        default=None,
        help="Porta inicial da tela local. Se omitida, usa PORTA_SERVIDOR_GERENCIAMENTO do .env.",
    )
    parser_gerenciar.add_argument(
        "--no-browser",
        action="store_true",
        help="Não tenta abrir o navegador automaticamente.",
    )

    return parser


def main() -> None:
    parser = criar_parser()
    args = parser.parse_args()

    if args.comando == "gerenciar":
        from config import PORTA_SERVIDOR_GERENCIAMENTO
        from tela_gerenciamento import abrir_tela_gerenciamento

        abrir_tela_gerenciamento(
            host=args.host,
            porta=args.porta if args.porta is not None else PORTA_SERVIDOR_GERENCIAMENTO,
            abrir_navegador=not args.no_browser,
        )
        return

    from app import main as baixar_imagens

    baixar_imagens()


if __name__ == "__main__":
    main()
