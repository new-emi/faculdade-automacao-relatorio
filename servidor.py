"""Microsservico HTTP do Boletim IA (Etapa 2 - AI Factory).
Expoe o pipeline da Etapa 1 como uma API local para o n8n orquestrar.
Rotas:
  GET /saude  -> status do servico (usado tambem nos testes de stress)
  GET /gerar  -> executa main.py, consulta o boletim.db e retorna JSON
  GET /audio  -> serve o WAV do dia como binario (para o n8n baixar)
Uso (com o Ollama ativo, em um terminal proprio):
  python servidor.py
A porta pode ser mudada por variavel de ambiente: BOLETIM_PORTA=9000 python servidor.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PORTA = int(os.environ.get("BOLETIM_PORTA", "8787"))
TEMPO_LIMITE_S = 900  # teto de 15 min por execucao do pipeline


def _ultimo_boletim() -> dict:
    """Le a linha mais recente da tabela boletins (roteiro + metadados)."""
    try:
        con = sqlite3.connect(str(RAIZ / "boletim.db"))
        try:
            linha = con.execute(
                "SELECT id, qtd_noticias, texto_boletim, duracao_audio_segundos "
                "FROM boletins ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        if not linha:
            return {}
        return {
            "id_boletim": linha[0],
            "qtd_noticias": linha[1],
            "roteiro": linha[2],
            "duracao_audio_s": round(linha[3], 2),
        }
    except Exception as erro:
        return {"erro_db": str(erro)}


class Handler(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, payload: dict) -> None:
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:
        inicio = time.time()

        if self.path == "/saude":
            self._responder(200, {
                "ok": True,
                "servico": "boletim-ia",
                "hora": datetime.now().isoformat(timespec="seconds"),
            })
            return

        if self.path == "/gerar":
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] GET /gerar -> executando main.py...", flush=True)
            try:
                proc = subprocess.run(
                    [sys.executable, "main.py"],
                    cwd=str(RAIZ),
                    capture_output=True,
                    timeout=TEMPO_LIMITE_S,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                self._responder(504, {"ok": False, "erro": f"timeout: main.py passou de {TEMPO_LIMITE_S}s"})
                return
            except Exception as erro:
                self._responder(500, {"ok": False, "erro": str(erro)})
                return

            def _extrair_motivo() -> str:
                """Pega a ultima linha util do stdout (a que comeca com [erro] ou [aviso])."""
                linhas = (proc.stdout or "").splitlines()
                # procura a ultima linha que comeca com [erro] ou [aviso]
                for linha in reversed(linhas):
                    limpa = linha.strip()
                    if limpa.startswith("[erro]") or limpa.startswith("[aviso]"):
                        # remove o prefixo [erro] ou [aviso] para ficar mais limpo
                        return limpa.lstrip("[erro] [aviso]").strip()
                # se nao achou nada especifico, pega a ultima linha nao vazia
                return linhas[-1].strip() if linhas else "erro desconhecido"

            gasto = round(time.time() - inicio, 2)
            ok = proc.returncode == 0
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] /gerar ok={ok} em {gasto}s", flush=True)

            payload = {
                "ok": ok,
                "codigo_saida": proc.returncode,
                "duracao_requisicao_s": gasto,
                "motivo": _extrair_motivo() if not ok else None,
            }
            if not ok:
                payload["erro_completo"] = (proc.stderr or proc.stdout or "")[-500:]
            else:
                payload.update(_ultimo_boletim())
            self._responder(200, payload)
            return

        if self.path == "/audio":
            caminho = RAIZ / "audio" / f"boletim_{datetime.now():%Y-%m-%d}.wav"
            if not caminho.is_file():
                self._responder(404, {"ok": False, "erro": f"audio do dia nao encontrado: {caminho.name}"})
                return
            dados = caminho.read_bytes()
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] GET /audio -> servindo {caminho.name} ({len(dados)} B)", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Content-Disposition", f'attachment; filename="{caminho.name}"')
            self.end_headers()
            self.wfile.write(dados)
            return

        self._responder(404, {"ok": False, "erro": "rota nao encontrada"})

    def log_message(self, formato, *args) -> None:  # log enxuto com horario
        print(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {formato % args}", flush=True)


if __name__ == "__main__":
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"Microsservico Boletim IA ouvindo em http://127.0.0.1:{PORTA}  (Ctrl+C para parar)")
    servidor.serve_forever()