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
       python teste.py

  4. Para rodar o script no WSL2
        Primeiro crie o ambiente dentro do linux
            python3 -m venv venv
            source venv/bin/activate
        Depois rode os comandos de instalação dos pacotes normalmente
            pip install requests pillow tqdm ddgs oracledb

  ATENÇÃO: As imagens serão salvas em PNG com o fundo original preservado.
=============================================================
"""

from app import main


if __name__ == "__main__":
    main()
