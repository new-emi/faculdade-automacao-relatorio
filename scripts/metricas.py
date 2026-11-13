"""Calcula as metricas da etapa final do Boletim IA a partir do boletim.db.

Le as tabelas `requisicoes` (gravada pelo servidor.py), `execucoes` (gravada pelo
main.py) e `boletins`, calcula latencia, taxa de sucesso, tempo por etapa, teste de
carga, teste de concorrencia e ROI, e grava tudo em docs/dashboard/dados.js, que o
dashboard (docs/dashboard/index.html) le ao abrir.

Uso (a partir da raiz do projeto):
    python scripts/metricas.py

Rode de novo sempre que houver execucoes novas: o dashboard se atualiza sozinho.
Usa so a biblioteca padrao (sqlite3, statistics, json).
"""
from __future__ import annotations

import io
import json
import sqlite3
import statistics as st
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CAMINHO_DB = RAIZ / "boletim.db"
SAIDA = RAIZ / "docs" / "dashboard" / "dados.js"

# Recortes da amostra (ids da tabela `requisicoes`), definidos pelo desenho do experimento:
#   amostra padrao  -> carga de producao (5 por fonte), todas as execucoes bem-sucedidas
#   teste de carga  -> ids 13 a 17: 2, 4, 6, 8 e 10 por fonte, com 5 min de pausa entre elas
#   concorrencia    -> ids 18 a 20: tres chamadas disparadas no mesmo segundo
IDS_CARGA = range(13, 18)
IDS_CONCORRENCIA = range(18, 21)

# Fase de desenvolvimento (Etapa 2), transcrita da aba Executions do n8n em 10/11/2026.
# O n8n nao grava esses dados no boletim.db; os 6 erros de 15 min foram testes de stress
# feitos de proposito (60 noticias, 3 disparos simultaneos, em 18/10 e 19/10).
HISTORICO_N8N = {"total": 23, "sucesso": 8, "stress_intencional": 6, "periodo": "18/10 a 19/10/2026"}
STRESS_ANTIGO = {"chamadas": 3, "timeout_s": 900, "boletins": 0, "noticias": 60}

# Experimento controlado (12/11/2026): os roteiros destas requisicoes foram sintetizados
# de novo pelo mesmo src/audio.py e o mesmo Kokoro numa maquina estavel (2 vCPUs, so CPU).
# Valor = segundos de processamento por segundo de audio. Nenhum trecho acionou a
# re-sintese por loop. Reproduzir com: python scripts/experimento_tts.py 17 16 12 15
EXPERIMENTO_CONTROLADO = {17: 0.68, 16: 0.68, 12: 0.67, 15: 0.68}

# Premissas do ROI (declaradas pela autora; ver README, secao de metricas).
ROI = {
    "manual_min_dia": [20, 35],      # curadoria manual antes da automacao (estimativa)
    "investimento_h": [12, 15],      # horas de construcao do projeto (estimativa)
    "dias_mes": 22,                  # dias uteis de uso por mes
    "manutencao_h_mes": 1,           # cenario de sensibilidade
}


def _mediana(valores):
    valores = [v for v in valores if v is not None]
    return round(st.median(valores), 2) if valores else None


def carregar(caminho_db: Path) -> list[dict]:
    with closing(sqlite3.connect(f"file:{caminho_db}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        linhas = con.execute(
            "SELECT r.*, b.duracao_audio_segundos AS audio_s, length(b.texto_boletim) AS roteiro_chars "
            "FROM requisicoes r LEFT JOIN boletins b ON b.id = r.id_boletim ORDER BY r.id"
        ).fetchall()
        execucoes = con.execute("SELECT status, count(*) FROM execucoes GROUP BY status").fetchall()
    return [dict(l) for l in linhas], {s: n for s, n in execucoes}


def calcular(reqs: list[dict], execucoes: dict) -> dict:
    sucesso = [r for r in reqs if r["status"] == "sucesso"]
    for r in sucesso:
        r["s_por_s_audio"] = round(r["t_audio_s"] / r["audio_s"], 2) if r["audio_s"] else None

    padrao = [r for r in sucesso if r["max_por_fonte"] == 5]
    latencias = [r["duracao_s"] for r in padrao]
    etapas = {e: _mediana([r[f"t_{e}_s"] for r in padrao]) for e in ("coleta", "roteiro", "audio", "registro")}
    total_etapas = sum(v for v in etapas.values() if v)
    escuta_min = _mediana([r["audio_s"] for r in padrao]) / 60

    # pipeline de verdade = tudo que nao foi recusado pela fila
    pipeline = [r for r in reqs if r["status"] != "ocupado"]

    def roi(manual, investimento, manutencao=0):
        poupado_mes = (manual - escuta_min) * ROI["dias_mes"] / 60 - manutencao
        ano = poupado_mes * 12
        return {
            "poupado_h_mes": round(poupado_mes, 1),
            "poupado_h_ano": round(ano, 1),
            "payback_meses": round(investimento / poupado_mes, 1),
            "roi_12m_pct": round((ano - investimento) / investimento * 100),
        }

    (m_min, m_max), (i_min, i_max) = ROI["manual_min_dia"], ROI["investimento_h"]
    concorrencia = [r for r in reqs if r["id"] in IDS_CONCORRENCIA]

    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "periodo": [reqs[0]["inicio"], reqs[-1]["inicio"]],
        "requisicoes_total": len(reqs),
        "sucesso": {
            "pipeline_ok": sum(1 for r in pipeline if r["status"] == "sucesso"),
            "pipeline_total": len(pipeline),
            "recusadas_fila": sum(1 for r in reqs if r["status"] == "ocupado"),
            "execucoes_main": execucoes,
            "desenvolvimento": HISTORICO_N8N,
        },
        "latencia": {
            "n": len(latencias),
            "mediana_s": _mediana(latencias),
            "min_s": round(min(latencias), 2),
            "max_s": round(max(latencias), 2),
            "media_s": round(st.mean(latencias), 2),
            "desvio_s": round(st.stdev(latencias), 2),
        },
        "etapas_mediana_s": etapas,
        "etapas_pct": {e: round(v / total_etapas * 100, 1) for e, v in etapas.items()},
        "escuta_mediana_min": round(escuta_min, 2),
        "carga": [
            {k: r[k] for k in ("id", "max_por_fonte", "qtd_noticias", "duracao_s", "t_coleta_s",
                               "t_roteiro_s", "t_audio_s", "s_por_s_audio", "roteiro_chars")}
            for r in sucesso if r["id"] in IDS_CARGA
        ],
        "stress_antigo": STRESS_ANTIGO,
        "concorrencia": [{"status": r["status"], "duracao_s": r["duracao_s"]} for r in concorrencia],
        "tts_variacao": [
            {"id": r["id"], "inicio": r["inicio"], "s_por_s_audio": r["s_por_s_audio"],
             "controlado": EXPERIMENTO_CONTROLADO.get(r["id"])}
            for r in sucesso
        ],
        "roi": {
            "premissas": ROI,
            "pessimista": roi(m_min, i_max),
            "otimista": roi(m_max, i_min),
            "pessimista_com_manutencao": roi(m_min, i_max, ROI["manutencao_h_mes"]),
            "otimista_com_manutencao": roi(m_max, i_min, ROI["manutencao_h_mes"]),
        },
        "tabela": [
            {k: r.get(k) for k in ("id", "inicio", "status", "max_por_fonte", "qtd_noticias", "duracao_s",
                                   "t_coleta_s", "t_roteiro_s", "t_audio_s", "audio_s", "etapa_falha")}
            for r in reqs
        ],
    }


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else CAMINHO_DB
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else SAIDA
    reqs, execucoes = carregar(db)
    metricas = calcular(reqs, execucoes)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(
        "// Gerado por scripts/metricas.py a partir do boletim.db. Nao edite a mao.\n"
        f"window.METRICAS = {json.dumps(metricas, ensure_ascii=False, indent=1)};\n",
        encoding="utf-8",
    )
    s, l, r = metricas["sucesso"], metricas["latencia"], metricas["roi"]
    print(f"[ok] {metricas['requisicoes_total']} requisicoes lidas -> {saida}")
    print(f"     sucesso do pipeline: {s['pipeline_ok']}/{s['pipeline_total']} "
          f"(+{s['recusadas_fila']} recusadas pela fila)")
    print(f"     latencia mediana (n={l['n']}): {l['mediana_s']} s  [{l['min_s']} a {l['max_s']} s]")
    print(f"     etapas (%): {metricas['etapas_pct']}")
    print(f"     ROI 12 meses: {r['pessimista']['roi_12m_pct']}% a {r['otimista']['roi_12m_pct']}%")
