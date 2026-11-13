"""Experimento controlado do TTS: o mesmo roteiro demora o mesmo tempo?

Pega roteiros ja gravados no boletim.db (pelo id da tabela `requisicoes`), sintetiza de
novo cada um com o src/audio.py do projeto e mede quantos segundos de processamento o
Kokoro gasta por segundo de audio. Conta tambem quantas vezes a re-sintese por loop foi
acionada (o aviso "repeticao detectada" do audio.py).

Se o mesmo roteiro levar tempos parecidos aqui e tempos muito diferentes no historico,
a variacao do historico veio do AMBIENTE (maquina quente, outros programas), nao do
codigo nem do texto.

Uso (a partir da raiz, com os modelos em models/):
    python scripts/experimento_tts.py 17 16 12 15
Os WAVs de teste vao para output/experimento/ (fora do git).
"""
from __future__ import annotations

import contextlib
import io
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

import soundfile as sf

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.audio import _carregar_kokoro, sintetizar_audio  # noqa: E402

SAIDA = RAIZ / "output" / "experimento"


def main(ids: list[int]) -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    _carregar_kokoro()  # carrega o modelo antes de medir, para nao contar o load
    with closing(sqlite3.connect(str(RAIZ / "boletim.db"))) as con:
        for rid in ids:
            linha = con.execute(
                "SELECT round(r.t_audio_s / b.duracao_audio_segundos, 2), b.texto_boletim "
                "FROM requisicoes r JOIN boletins b ON b.id = r.id_boletim WHERE r.id = ?",
                (rid,),
            ).fetchone()
            if not linha:
                print(f"req {rid}: nao encontrada ou sem boletim")
                continue
            historico, texto = linha
            destino = SAIDA / f"req{rid}.wav"
            console = io.StringIO()
            inicio = time.perf_counter()
            with contextlib.redirect_stdout(console):
                sintetizar_audio(texto, str(destino))
            gasto = time.perf_counter() - inicio
            duracao = sf.info(str(destino)).duration
            resinteses = console.getvalue().count("repeticao detectada")
            print(
                f"req {rid}: historico={historico} s/s  agora={gasto / duracao:.2f} s/s  "
                f"re-sinteses por loop={resinteses}"
            )


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [17, 16, 12, 15])
