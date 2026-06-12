import json
import logging
import mimetypes
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

from gerenciador_imagens import (
    arquivo_local_por_nome,
    excluir_imagens_locais,
    listar_imagens_pendentes,
    salvar_imagens_selecionadas,
)


log = logging.getLogger(__name__)

CAMINHO_BASE = "/intellisys-images"


HTML_GERENCIAMENTO = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gerenciamento de imagens</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --surface: #ffffff;
      --surface-soft: #eef2f4;
      --text: #172026;
      --muted: #66727c;
      --line: #d9e0e4;
      --primary: #116a64;
      --primary-strong: #0b4e49;
      --danger: #b42318;
      --danger-soft: #fff0ed;
      --ok-soft: #eaf7ef;
      --shadow: 0 8px 24px rgba(17, 32, 38, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    header {
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid var(--line);
      background: rgba(245, 247, 248, 0.94);
      backdrop-filter: blur(12px);
    }

    .topbar {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      max-width: 1240px;
      margin: 0 auto;
      padding: 16px 20px;
    }

    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      max-width: 1240px;
      margin: 0 auto;
      padding: 0 20px 16px;
    }

    button {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      font-size: 14px;
      font-weight: 650;
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease, transform 0.15s ease;
    }

    button:hover:not(:disabled) {
      border-color: #9aabb3;
      transform: translateY(-1px);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }

    .primary {
      border-color: var(--primary);
      background: var(--primary);
      color: #ffffff;
    }

    .primary:hover:not(:disabled) {
      border-color: var(--primary-strong);
      background: var(--primary-strong);
    }

    .danger {
      border-color: #f0b8b2;
      background: var(--danger-soft);
      color: var(--danger);
    }

    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 20px;
    }

    .status {
      min-height: 38px;
      display: none;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      padding: 10px 12px;
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 16px;
    }

    .status.visible {
      display: flex;
    }

    .status.ok {
      border-color: #b8ddc5;
      background: var(--ok-soft);
      color: #1f663d;
    }

    .status.error {
      border-color: #f0b8b2;
      background: var(--danger-soft);
      color: var(--danger);
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 14px;
    }

    .card {
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }

    .card.selected {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(17, 106, 100, 0.16), var(--shadow);
    }

    .thumb {
      display: grid;
      place-items: center;
      aspect-ratio: 1;
      background:
        linear-gradient(45deg, #edf1f3 25%, transparent 25%),
        linear-gradient(-45deg, #edf1f3 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #edf1f3 75%),
        linear-gradient(-45deg, transparent 75%, #edf1f3 75%);
      background-color: #ffffff;
      background-position: 0 0, 0 10px, 10px -10px, -10px 0;
      background-size: 20px 20px;
    }

    .thumb img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      padding: 8px;
    }

    .check {
      position: absolute;
      top: 8px;
      left: 8px;
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      border-radius: 7px;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid var(--line);
    }

    .check input {
      width: 17px;
      height: 17px;
      accent-color: var(--primary);
      cursor: pointer;
    }

    .info {
      display: grid;
      gap: 5px;
      padding: 10px;
      border-top: 1px solid var(--line);
    }

    .filename {
      overflow: hidden;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .details {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: 260px;
      border: 1px dashed #aebbc2;
      border-radius: 8px;
      background: var(--surface);
      color: var(--muted);
      font-size: 15px;
      text-align: center;
      padding: 24px;
    }

    @media (max-width: 640px) {
      .topbar {
        grid-template-columns: 1fr;
        gap: 8px;
      }

      .meta {
        justify-content: flex-start;
        white-space: normal;
      }

      .toolbar {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      button {
        width: 100%;
      }

      main {
        padding: 14px;
      }

      .grid {
        grid-template-columns: repeat(auto-fill, minmax(145px, 1fr));
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <h1>Imagens locais</h1>
      <div class="meta">
        <span id="total">0 pendentes</span>
        <span id="selected">0 selecionadas</span>
      </div>
    </div>
    <div class="toolbar">
      <button id="reload" type="button">Atualizar</button>
      <button id="selectAll" type="button">Selecionar todas</button>
      <button id="clearAll" type="button">Desmarcar todas</button>
      <button id="save" type="button" class="primary">Salvar selecionadas</button>
      <button id="delete" type="button" class="danger">Excluir selecionadas</button>
    </div>
  </header>

  <main>
    <div id="status" class="status"></div>
    <section id="grid" class="grid" aria-live="polite"></section>
  </main>

  <script>
    const state = {
      imagens: [],
      selecionadas: new Set(),
      carregando: false
    };

    const grid = document.getElementById("grid");
    const statusEl = document.getElementById("status");
    const totalEl = document.getElementById("total");
    const selectedEl = document.getElementById("selected");
    const saveBtn = document.getElementById("save");
    const deleteBtn = document.getElementById("delete");
    const BASE_PATH = "/intellisys-images";

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function plural(total, singular, pluralLabel) {
      return `${total} ${total === 1 ? singular : pluralLabel}`;
    }

    function setStatus(message, type = "") {
      statusEl.textContent = message || "";
      statusEl.className = `status${message ? " visible" : ""}${type ? ` ${type}` : ""}`;
    }

    function updateCounters() {
      totalEl.textContent = plural(state.imagens.length, "pendente", "pendentes");
      selectedEl.textContent = plural(state.selecionadas.size, "selecionada", "selecionadas");
      saveBtn.disabled = state.selecionadas.size === 0 || state.carregando;
      deleteBtn.disabled = state.selecionadas.size === 0 || state.carregando;
    }

    function render() {
      updateCounters();

      if (!state.imagens.length) {
        grid.className = "empty";
        grid.innerHTML = "Nenhuma imagem pendente.";
        return;
      }

      grid.className = "grid";
      grid.innerHTML = state.imagens.map((imagem) => {
        const checked = state.selecionadas.has(imagem.nome_arquivo);
        return `
          <article class="card${checked ? " selected" : ""}" data-file="${escapeHtml(imagem.nome_arquivo)}">
            <label class="check" aria-label="Selecionar ${escapeHtml(imagem.nome_arquivo)}">
              <input type="checkbox" ${checked ? "checked" : ""}>
            </label>
            <div class="thumb">
              <img src="${escapeHtml(imagem.url)}" alt="${escapeHtml(imagem.nome_arquivo)}" loading="lazy">
            </div>
            <div class="info">
              <div class="filename" title="${escapeHtml(imagem.nome_arquivo)}">${escapeHtml(imagem.nome_arquivo)}</div>
              <div class="details">
                <span>${escapeHtml(imagem.codigo)}</span>
                <span>${escapeHtml(imagem.tamanho)}</span>
                <span>${escapeHtml(imagem.atualizado_em)}</span>
              </div>
            </div>
          </article>
        `;
      }).join("");
    }

    async function carregar() {
      state.carregando = true;
      updateCounters();
      setStatus("Carregando imagens locais...");

      try {
        const response = await fetch(`${BASE_PATH}/api/imagens`, { cache: "no-store" });
        const payload = await response.json();

        if (!response.ok) {
          throw new Error(payload.erro || "Erro ao carregar imagens.");
        }

        state.imagens = payload.imagens || [];
        state.selecionadas = new Set(
          [...state.selecionadas].filter((nome) =>
            state.imagens.some((imagem) => imagem.nome_arquivo === nome)
          )
        );
        setStatus("");
        render();
      } catch (error) {
        state.imagens = [];
        state.selecionadas.clear();
        render();
        setStatus(error.message, "error");
      } finally {
        state.carregando = false;
        updateCounters();
      }
    }

    async function enviarAcao(endpoint, arquivos) {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ arquivos })
      });
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.erro || "Erro ao processar seleção.");
      }

      return payload;
    }

    async function salvarSelecionadas() {
      const arquivos = [...state.selecionadas];
      if (!arquivos.length) return;

      state.carregando = true;
      updateCounters();
      setStatus("Salvando imagens selecionadas...");

      try {
        const payload = await enviarAcao(`${BASE_PATH}/api/salvar`, arquivos);
        const resumo = payload.resumo || {};
        const partes = [
          plural(resumo.inseridas || 0, "inserida", "inseridas"),
          plural(resumo.ja_existiam || 0, "já existente", "já existentes"),
          plural(resumo.removidas || 0, "arquivo removido", "arquivos removidos")
        ];

        if (resumo.falhas_persistencia || resumo.falhas_remocao || (payload.erros || []).length) {
          partes.push(plural((resumo.falhas_persistencia || 0) + (resumo.falhas_remocao || 0) + (payload.erros || []).length, "falha", "falhas"));
        }

        const falhou = resumo.falhas_persistencia || resumo.falhas_remocao || (payload.erros || []).length;
        const mensagem = partes.join(", ") + ".";
        state.selecionadas.clear();
        await carregar();
        setStatus(mensagem, falhou ? "error" : "ok");
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        state.carregando = false;
        updateCounters();
      }
    }

    async function excluirSelecionadas() {
      const arquivos = [...state.selecionadas];
      if (!arquivos.length) return;

      if (!confirm(`Excluir ${plural(arquivos.length, "arquivo local", "arquivos locais")}?`)) {
        return;
      }

      state.carregando = true;
      updateCounters();
      setStatus("Excluindo arquivos locais...");

      try {
        const payload = await enviarAcao(`${BASE_PATH}/api/excluir`, arquivos);
        const resumo = payload.resumo || {};
        const mensagem = `${plural(resumo.removidas || 0, "arquivo removido", "arquivos removidos")}, ${plural(resumo.falhas || 0, "falha", "falhas")}.`;
        state.selecionadas.clear();
        await carregar();
        setStatus(mensagem, resumo.falhas ? "error" : "ok");
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        state.carregando = false;
        updateCounters();
      }
    }

    grid.addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[type='checkbox']");
      if (!checkbox) return;

      const card = event.target.closest(".card");
      const nome = card?.dataset.file;
      if (!nome) return;

      if (checkbox.checked) {
        state.selecionadas.add(nome);
      } else {
        state.selecionadas.delete(nome);
      }

      render();
    });

    grid.addEventListener("click", (event) => {
      if (event.target.matches("input[type='checkbox']")) return;
      const card = event.target.closest(".card");
      const nome = card?.dataset.file;
      if (!nome) return;

      if (state.selecionadas.has(nome)) {
        state.selecionadas.delete(nome);
      } else {
        state.selecionadas.add(nome);
      }

      render();
    });

    document.getElementById("reload").addEventListener("click", carregar);
    document.getElementById("selectAll").addEventListener("click", () => {
      state.selecionadas = new Set(state.imagens.map((imagem) => imagem.nome_arquivo));
      render();
    });
    document.getElementById("clearAll").addEventListener("click", () => {
      state.selecionadas.clear();
      render();
    });
    saveBtn.addEventListener("click", salvarSelecionadas);
    deleteBtn.addEventListener("click", excluirSelecionadas);

    carregar();
  </script>
</body>
</html>
"""


def resposta_json(handler: BaseHTTPRequestHandler, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
    conteudo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(conteudo)))
    handler.end_headers()
    handler.wfile.write(conteudo)


def resposta_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    conteudo = html.encode("utf-8")
    handler.send_response(HTTPStatus.OK.value)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(conteudo)))
    handler.end_headers()
    handler.wfile.write(conteudo)


def resposta_redirect(handler: BaseHTTPRequestHandler, destino: str) -> None:
    handler.send_response(HTTPStatus.FOUND.value)
    handler.send_header("Location", destino)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def imagem_para_json(imagem) -> dict:
    atualizado = datetime.fromtimestamp(imagem.atualizado_em).strftime("%d/%m/%Y %H:%M")
    tamanho_kb = max(1, round(imagem.tamanho_bytes / 1024))
    return {
        "codigo": imagem.codigo,
        "nome_arquivo": imagem.nome_arquivo,
        "url": f"{CAMINHO_BASE}/imagem/{quote(imagem.nome_arquivo, safe='')}?v={int(imagem.atualizado_em)}",
        "tamanho": f"{tamanho_kb} KB",
        "atualizado_em": atualizado,
    }


def ler_json_body(handler: BaseHTTPRequestHandler) -> dict:
    tamanho = int(handler.headers.get("Content-Length", "0") or "0")

    if tamanho > 1_000_000:
        raise ValueError("requisição muito grande")

    if tamanho <= 0:
        return {}

    conteudo = handler.rfile.read(tamanho).decode("utf-8")
    return json.loads(conteudo)


def arquivos_da_requisicao(handler: BaseHTTPRequestHandler) -> list[str]:
    payload = ler_json_body(handler)
    arquivos = payload.get("arquivos", [])

    if not isinstance(arquivos, list):
        raise ValueError("campo 'arquivos' deve ser uma lista")

    return [str(arquivo) for arquivo in arquivos]


def json_resultado_gerenciamento(resultado) -> dict:
    return {
        "resumo": {
            "inseridas": resultado.inseridas,
            "ja_existiam": resultado.ja_existiam,
            "falhas_persistencia": resultado.falhas_persistencia,
            "removidas": resultado.removidas,
            "falhas_remocao": resultado.falhas_remocao,
        },
        "persistencias": [
            {
                "codigo": item.codigo,
                "nome_arquivo": item.caminho.name,
                "status": item.status,
                "erro": item.erro,
            }
            for item in resultado.persistencias
        ],
        "remocoes": [
            {
                "nome_arquivo": item.nome_arquivo,
                "removida": item.removida,
                "erro": item.erro,
            }
            for item in resultado.remocoes
        ],
        "erros": resultado.erros,
    }


class GerenciamentoImagensHandler(BaseHTTPRequestHandler):
    server_version = "GerenciadorImagens/1.0"

    def log_message(self, formato: str, *args) -> None:
        log.info("Tela de gerenciamento: " + formato, *args)

    def do_GET(self) -> None:
        rota = urlparse(self.path)
        caminho = rota.path

        if caminho == "/":
            resposta_redirect(self, CAMINHO_BASE)
            return

        if caminho in {CAMINHO_BASE, f"{CAMINHO_BASE}/"}:
            resposta_html(self, HTML_GERENCIAMENTO)
            return

        if caminho == f"{CAMINHO_BASE}/api/imagens":
            self.enviar_lista_imagens()
            return

        prefixo_imagem = f"{CAMINHO_BASE}/imagem/"
        if caminho.startswith(prefixo_imagem):
            self.enviar_imagem(caminho.removeprefix(prefixo_imagem))
            return

        resposta_json(self, {"erro": "rota não encontrada"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        rota = urlparse(self.path)

        try:
            if rota.path == f"{CAMINHO_BASE}/api/salvar":
                arquivos = arquivos_da_requisicao(self)
                resultado = salvar_imagens_selecionadas(arquivos)
                resposta_json(self, json_resultado_gerenciamento(resultado))
                return

            if rota.path == f"{CAMINHO_BASE}/api/excluir":
                arquivos = arquivos_da_requisicao(self)
                resultados = excluir_imagens_locais(arquivos)
                resposta_json(
                    self,
                    {
                        "resumo": {
                            "removidas": sum(1 for item in resultados if item.removida),
                            "falhas": sum(1 for item in resultados if not item.removida),
                        },
                        "remocoes": [
                            {
                                "nome_arquivo": item.nome_arquivo,
                                "removida": item.removida,
                                "erro": item.erro,
                            }
                            for item in resultados
                        ],
                    },
                )
                return

            resposta_json(self, {"erro": "rota não encontrada"}, HTTPStatus.NOT_FOUND)
        except Exception as e:
            log.warning(f"Erro ao processar ação da tela de gerenciamento: {e}", exc_info=True)
            resposta_json(self, {"erro": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def enviar_lista_imagens(self) -> None:
        try:
            imagens = [imagem_para_json(imagem) for imagem in listar_imagens_pendentes()]
            resposta_json(self, {"imagens": imagens, "total": len(imagens)})
        except Exception as e:
            log.warning(f"Erro ao listar imagens pendentes: {e}", exc_info=True)
            resposta_json(self, {"erro": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def enviar_imagem(self, nome_url: str) -> None:
        try:
            nome_arquivo = unquote(nome_url)
            caminho = arquivo_local_por_nome(nome_arquivo)
            conteudo = caminho.read_bytes()
            tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"

            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            self.wfile.write(conteudo)
        except Exception as e:
            log.warning(f"Erro ao servir pré-visualização de imagem: {e}", exc_info=True)
            resposta_json(self, {"erro": str(e)}, HTTPStatus.NOT_FOUND)


def criar_servidor(host: str, porta_inicial: int) -> ThreadingHTTPServer:
    tentativas = range(porta_inicial, porta_inicial + 20) if porta_inicial else (0,)

    for porta in tentativas:
        try:
            return ThreadingHTTPServer((host, porta), GerenciamentoImagensHandler)
        except OSError as e:
            log.warning(f"Porta {porta} indisponível para a tela de gerenciamento: {e}")

    raise RuntimeError("não foi possível iniciar a tela de gerenciamento em uma porta disponível")


def abrir_tela_gerenciamento(
    host: str = "127.0.0.1",
    porta: int = 8000,
    abrir_navegador: bool = True,
) -> None:
    """Inicia a tela local de gerenciamento de imagens."""
    servidor = criar_servidor(host, porta)
    host_url = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    url = f"http://{host_url}:{servidor.server_address[1]}{CAMINHO_BASE}"
    log.info(f"Tela de gerenciamento disponível em: {url}")

    if abrir_navegador:
        webbrowser.open(url)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("Tela de gerenciamento encerrada pelo usuário.")
    finally:
        servidor.server_close()
