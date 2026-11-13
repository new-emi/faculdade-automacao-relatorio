"""Microsservico HTTP do Boletim IA (Etapas 2 e 3 - AI Factory).

Expoe o pipeline da Etapa 1 como uma API local para o n8n orquestrar e, desde a
etapa final, registra cada chamada ao /gerar na tabela `requisicoes` do boletim.db
(instrumentacao: o proprio sistema mede latencia, sucesso e tempo de cada etapa).

Duas camadas de auditoria no mesmo banco:
  - `execucoes`  (gravada pelo main.py / src/registro.py): o que o PIPELINE fez.
  - `requisicoes` (gravada aqui): o que o n8n PEDIU e quanto tempo levou. So esta
    camada enxerga timeout, fila ocupada e Python sem pacotes, porque nesses casos
    o main.py morre ou nem comeca, e nao tem como se registrar.

Rotas:
  GET /saude                 -> status do servico (inclui se o pipeline esta ocupado)
  GET /gerar                 -> executa main.py, registra a requisicao e retorna JSON
  GET /gerar?max_por_fonte=8 -> idem, com outra carga (usado nos testes de carga)
  GET /audio                 -> serve o WAV do dia como binario (para o n8n baixar)

Uso (com o Ollama ativo, em um terminal proprio):
  python servidor.py

Variaveis de ambiente (todas opcionais):
  BOLETIM_PORTA   porta HTTP (padrao 8787)
  BOLETIM_PYTHON  interpretador que roda o main.py (padrao: o mesmo deste servidor).
                  Fixa o Python certo e evita o drift de ambiente visto na Etapa 2.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent
CAMINHO_DB = RAIZ / "boletim.db"
PORTA = int(os.environ.get("BOLETIM_PORTA", "8787"))
PYTHON_PIPELINE = os.environ.get("BOLETIM_PYTHON", sys.executable)
TEMPO_LIMITE_S = 900  # teto de 15 min por execucao do pipeline
MAX_POR_FONTE_PADRAO = 5
MAX_POR_FONTE_LIMITE = 30  # protege a maquina de uma carga absurda vinda pela URL

# Fila de um worker so: o gargalo e a GPU/LLM local, entao duas execucoes ao mesmo
# tempo so pioram as duas (medido no teste de stress da Etapa 2). Quem chega com o
# pipeline ocupado recebe "ocupado" na hora, em vez de esperar 15 min e cair no timeout.
TRAVA_PIPELINE = threading.Lock()

SQL_CRIAR_REQUISICOES = """
CREATE TABLE IF NOT EXISTS requisicoes (
    id INTEGER PRIMARY KEY,
    inicio TEXT,               -- data/hora em que o /gerar comecou
    duracao_s REAL,            -- latencia total da requisicao, em segundos
    ok INTEGER,                -- 1 = boletim gerado, 0 = falhou ou foi recusado
    status TEXT,               -- sucesso | falha | timeout | ocupado
    etapa_falha TEXT,          -- coleta | roteiro | audio | registro | ambiente | fila
    motivo TEXT,               -- mensagem curta do erro
    max_por_fonte INTEGER,     -- carga pedida
    qtd_noticias INTEGER,      -- noticias realmente usadas (so no sucesso)
    t_coleta_s REAL,           -- tempo de cada etapa, lido das linhas "[tempo]"
    t_roteiro_s REAL,
    t_audio_s REAL,
    t_registro_s REAL,
    id_boletim INTEGER         -- liga a requisicao a linha da tabela boletins
)
"""

# Marcadores que o main.py imprime ao entrar em cada etapa.
ETAPAS = {"[1/4]": "coleta", "[2/4]": "roteiro", "[3/4]": "audio", "[4/4]": "registro"}
RE_TEMPO = re.compile(r"^\[tempo\]\s+(\w+)\s+([\d.]+)")


def _agora() -> str:
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def inicializar_requisicoes() -> None:
    """Cria a tabela `requisicoes` se ela ainda nao existir."""
    with closing(sqlite3.connect(str(CAMINHO_DB))) as con, con:
        con.execute(SQL_CRIAR_REQUISICOES)


def registrar_requisicao(**campos) -> None:
    """Insere uma linha em `requisicoes`. Uma falha aqui nunca derruba a requisicao."""
    try:
        colunas = ", ".join(campos)
        marcas = ", ".join("?" for _ in campos)
        with closing(sqlite3.connect(str(CAMINHO_DB))) as con, con:
            con.execute(f"INSERT INTO requisicoes ({colunas}) VALUES ({marcas})", list(campos.values()))
    except Exception as erro:
        print(f"[{_agora()}] [aviso] nao consegui registrar a requisicao: {erro}", flush=True)


def _ultimo_boletim() -> dict:
    """Le a linha mais recente da tabela boletins (roteiro + metadados)."""
    try:
        with closing(sqlite3.connect(str(CAMINHO_DB))) as con:
            linha = con.execute(
                "SELECT id, qtd_noticias, texto_boletim, duracao_audio_segundos "
                "FROM boletins ORDER BY id DESC LIMIT 1"
            ).fetchone()
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


def _analisar_saida(stdout: str, stderr: str) -> dict:
    """Le o que o main.py imprimiu e extrai tempos por etapa, etapa da falha e motivo."""
    tempos: dict[str, float] = {}
    etapa_atual = None
    motivo = None
    for linha in stdout.splitlines():
        limpa = linha.strip()
        for marcador, nome in ETAPAS.items():
            if limpa.startswith(marcador):
                etapa_atual = nome
        achou = RE_TEMPO.match(limpa)
        if achou:
            tempos[achou.group(1)] = float(achou.group(2))
        for prefixo in ("[erro]", "[aviso]"):
            if limpa.startswith(prefixo):
                # removeprefix tira exatamente o texto "[erro]"; o antigo lstrip("[erro] [aviso]")
                # tirava LETRAS soltas do inicio e podia cortar o comeco da mensagem.
                motivo = limpa.removeprefix(prefixo).strip()
    if motivo is None:
        # o processo morreu antes de imprimir um [erro] (ex.: modulo faltando): olha o stderr
        erros = [l.strip() for l in stderr.splitlines() if "Error" in l or "Exception" in l]
        motivo = erros[-1] if erros else "erro desconhecido"
        if etapa_atual is None:
            etapa_atual = "ambiente"
    return {"tempos": tempos, "etapa_falha": etapa_atual, "motivo": motivo[:300]}


def _ler_max_por_fonte(caminho: str) -> int:
    """Le ?max_por_fonte=N da URL, dentro de limites seguros."""
    valores = parse_qs(urlparse(caminho).query).get("max_por_fonte")
    if not valores:
        return MAX_POR_FONTE_PADRAO
    try:
        return max(1, min(int(valores[0]), MAX_POR_FONTE_LIMITE))
    except ValueError:
        return MAX_POR_FONTE_PADRAO


class Handler(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, payload: dict) -> None:
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:
        rota = urlparse(self.path).path

        if rota == "/saude":
            self._responder(200, {
                "ok": True,
                "servico": "boletim-ia",
                "pipeline_ocupado": TRAVA_PIPELINE.locked(),
                "hora": datetime.now().isoformat(timespec="seconds"),
            })
            return

        if rota == "/gerar":
            self._gerar(_ler_max_por_fonte(self.path))
            return

        if rota == "/audio":
            caminho = RAIZ / "audio" / f"boletim_{datetime.now():%Y-%m-%d}.wav"
            if not caminho.is_file():
                self._responder(404, {"ok": False, "erro": f"audio do dia nao encontrado: {caminho.name}"})
                return
            dados = caminho.read_bytes()
            print(f"[{_agora()}] GET /audio -> servindo {caminho.name} ({len(dados)} B)", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Content-Disposition", f'attachment; filename="{caminho.name}"')
            self.end_headers()
            self.wfile.write(dados)
            return

        self._responder(404, {"ok": False, "erro": "rota nao encontrada"})

    def _gerar(self, max_por_fonte: int) -> None:
        inicio_txt = _agora()
        inicio = time.perf_counter()

        # Fila de um worker: se ja tem pipeline rodando, recusa na hora.
        if not TRAVA_PIPELINE.acquire(blocking=False):
            print(f"[{inicio_txt}] GET /gerar recusado: pipeline ocupado", flush=True)
            registrar_requisicao(
                inicio=inicio_txt, duracao_s=round(time.perf_counter() - inicio, 3), ok=0,
                status="ocupado", etapa_falha="fila", motivo="pipeline ocupado com outra execucao",
                max_por_fonte=max_por_fonte,
            )
            self._responder(200, {"ok": False, "status": "ocupado",
                                  "motivo": "ja existe um boletim sendo gerado; tente de novo em alguns minutos"})
            return

        try:
            print(f"[{inicio_txt}] GET /gerar (max_por_fonte={max_por_fonte}) -> executando main.py...", flush=True)
            ambiente = {**os.environ, "BOLETIM_MAX_POR_FONTE": str(max_por_fonte)}
            try:
                # "-u" = sem buffer: cada print sai na hora, entao ate um crash deixa rastro.
                proc = subprocess.run(
                    [PYTHON_PIPELINE, "-u", "main.py"],
                    cwd=str(RAIZ), env=ambiente, capture_output=True,
                    timeout=TEMPO_LIMITE_S, encoding="utf-8", errors="replace",
                )
            except subprocess.TimeoutExpired as estouro:
                gasto = round(time.perf_counter() - inicio, 2)
                parcial = estouro.stdout or ""
                if isinstance(parcial, bytes):
                    parcial = parcial.decode("utf-8", "replace")
                analise = _analisar_saida(parcial, "")
                registrar_requisicao(
                    inicio=inicio_txt, duracao_s=gasto, ok=0, status="timeout",
                    etapa_falha=analise["etapa_falha"], motivo=f"passou de {TEMPO_LIMITE_S}s",
                    max_por_fonte=max_por_fonte,
                    t_coleta_s=analise["tempos"].get("coleta"), t_roteiro_s=analise["tempos"].get("roteiro"),
                )
                self._responder(504, {"ok": False, "status": "timeout",
                                      "erro": f"timeout: main.py passou de {TEMPO_LIMITE_S}s"})
                return
            except Exception as erro:
                registrar_requisicao(
                    inicio=inicio_txt, duracao_s=round(time.perf_counter() - inicio, 2), ok=0,
                    status="falha", etapa_falha="ambiente", motivo=str(erro)[:300], max_por_fonte=max_por_fonte,
                )
                self._responder(500, {"ok": False, "status": "falha", "erro": str(erro)})
                return

            gasto = round(time.perf_counter() - inicio, 2)
            ok = proc.returncode == 0
            analise = _analisar_saida(proc.stdout or "", proc.stderr or "")
            t = analise["tempos"]
            print(f"[{_agora()}] /gerar ok={ok} em {gasto}s  etapas={t}", flush=True)

            payload = {
                "ok": ok,
                "status": "sucesso" if ok else "falha",
                "codigo_saida": proc.returncode,
                "duracao_requisicao_s": gasto,
                "tempos_etapas_s": t,
                "max_por_fonte": max_por_fonte,
            }
            if ok:
                payload.update(_ultimo_boletim())
            else:
                payload["etapa_falha"] = analise["etapa_falha"]
                payload["motivo"] = analise["motivo"]
                payload["erro_completo"] = (proc.stderr or proc.stdout or "")[-500:]

            registrar_requisicao(
                inicio=inicio_txt, duracao_s=gasto, ok=int(ok),
                status=payload["status"],
                etapa_falha=None if ok else analise["etapa_falha"],
                motivo=None if ok else analise["motivo"],
                max_por_fonte=max_por_fonte,
                qtd_noticias=payload.get("qtd_noticias"),
                t_coleta_s=t.get("coleta"), t_roteiro_s=t.get("roteiro"),
                t_audio_s=t.get("audio"), t_registro_s=t.get("registro"),
                id_boletim=payload.get("id_boletim"),
            )
            self._responder(200, payload)
        finally:
            TRAVA_PIPELINE.release()

    def log_message(self, formato, *args) -> None:  # log enxuto com horario
        print(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {formato % args}", flush=True)


if __name__ == "__main__":
    inicializar_requisicoes()
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"Microsservico Boletim IA ouvindo em http://127.0.0.1:{PORTA}  (Ctrl+C para parar)")
    print(f"Pipeline roda com: {PYTHON_PIPELINE}")
    servidor.serve_forever()
