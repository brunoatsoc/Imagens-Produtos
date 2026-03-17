import pandas as pd

# 1. Criamos uma pequena função para descobrir o separador
def ler_csv_flexivel(caminho):
    with open(caminho, 'r', encoding='latin1') as arquivo:
        primeira_linha = arquivo.readline()
        # Se tiver um ponto e vírgula na primeira linha, usa ele. Se não, usa a vírgula.
        separador = ';' if ';' in primeira_linha else ','
        
    # Agora sim, o pandas lê o arquivo usando o separador correto
    return pd.read_csv(caminho, sep=separador, encoding='latin1')

# 2. Usamos a função para ler os dois arquivos
df1 = ler_csv_flexivel('produtos1.csv')
df2 = ler_csv_flexivel('produtos2.csv')

# --- O resto do seu código continua exatamente igual ---

# Remove espaços extras
df1['nome_produto'] = df1['nome_produto'].str.strip()
df1['nome_imagem'] = df1['nome_imagem'].astype(str).str.strip()

df2['nome_produto'] = df2['nome_produto'].str.strip()
df2['nome_imagem'] = df2['nome_imagem'].astype(str).str.strip()

faltando = df2.merge(
    df1,
    on=['nome_produto', 'nome_imagem'],
    how='left',
    indicator=True
)

faltando = faltando[faltando['_merge'] == 'left_only']
faltando = faltando[df2.columns]

faltando.to_csv('faltando_no_arquivo1.csv', sep=';', index=False, encoding='latin1')

print("Arquivo gerado com sucesso!")