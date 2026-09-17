"""Orquestrador do pipeline "Boletim IA" (Input -> Process -> Output -> SQLite).

Encadeia as quatro etapas do projeto, a partir da raiz:

    1. Coleta   -> src.coletor.coletar_noticias        (HN + Reddit, sem chave de API)
    2. Roteiro  -> src.boletim.gerar_boletim          (LLM local qwen2.5:3b via Ollama)
    3. Audio    -> src.audio.sintetizar_audio         (Kokoro TTS, WAV 16-bit 24 kHz)
    4. Registro -> src.registro.registrar_boletim     (SQLite: boletim.db)

Uso (a partir da raiz do projeto, com o Ollama ativo):
    python main.py

Requisitos: Ollama em http://localhost:11434 com o modelo qwen2.5:3b baixado e os
modelos Kokoro em models/ (reconstruir com: python scripts/download_kokoro.py).
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

import soundfile as sf

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:  # garante "from src.*" mesmo rodando de outro cwd
    sys.path.insert(0, str(RAIZ))

from src.audio import sintetizar_audio
from src.boletim import gerar_boletim
from src.coletor import coletar_noticias
from src.registro import inicializar_banco, registrar_boletim

DIAS = 1
# 5 por fonte = ate 10 noticias por edicao; com 20 o modelo de 3B passou a omitir itens
# (ver README, limitacoes)
MAX_POR_FONTE = 5
CAMINHO_DB = "boletim.db"
PASTA_AUDIO = Path("audio")


def main() -> int:
    """Executa o pipeline completo e devolve o codigo de saida do processo."""
    agora = datetime.now()
    carimbo = agora.strftime("%Y-%m-%d %H:%M:%S")
    caminho_audio = PASTA_AUDIO / f"boletim_{agora:%Y-%m-%d}.wav"

    print("=" * 70)
    print(f"Boletim IA - {carimbo}")
    print("=" * 70)

    # a) banco de dados
    try:
        inicializar_banco(CAMINHO_DB)
    except Exception as erro:  # sqlite3.Error, permissao, disco, ...
        print(f"[erro] nao foi possivel inicializar o banco '{CAMINHO_DB}': {erro}")
        return 1

    # b) coleta
    print(f"\n[1/4] Coletando noticias (ultimos {DIAS} dia(s), ate {MAX_POR_FONTE} por fonte)...")
    try:
        noticias = coletar_noticias(dias=DIAS, max_por_fonte=MAX_POR_FONTE)
    except Exception as erro:
        print(f"[erro] falha na coleta de noticias: {erro}")
        return 1

    # c) sem noticias: encerra sem gerar boletim
    if not noticias:
        print(
            f"[aviso] nenhuma noticia coletada nos ultimos {DIAS} dia(s); "
            "encerrando sem gerar boletim (verifique a conexao de rede)."
        )
        return 1

    print(f"{len(noticias)} noticias coletadas.")

    # d) roteiro via LLM
    print("\n[2/4] Gerando o roteiro com o LLM local (qwen2.5:3b)...")
    try:
        texto = gerar_boletim(noticias)
    except Exception as erro:
        print(f"[erro] falha ao gerar o roteiro do boletim: {erro}")
        return 1

    print(f"Roteiro pronto ({len(texto)} caracteres).")

    # e/f) TTS -> WAV
    print(f"\n[3/4] Sintetizando o audio em '{caminho_audio.as_posix()}'...")
    try:
        destino = sintetizar_audio(texto, caminho_audio.as_posix())
    except Exception as erro:
        print(f"[erro] falha ao sintetizar o audio: {erro}")
        return 1

    # g) duracao real do WAV gravado
    try:
        amostras, taxa_amostragem = sf.read(str(destino))
        duracao = len(amostras) / float(taxa_amostragem)
    except Exception as erro:
        print(f"[erro] falha ao ler o WAV gerado em '{destino}': {erro}")
        return 1

    # h) registro no SQLite
    print(f"\n[4/4] Registrando o boletim em '{CAMINHO_DB}'...")
    try:
        id_boletim = registrar_boletim(
            CAMINHO_DB,
            data_geracao=carimbo,
            qtd_noticias=len(noticias),
            texto_boletim=texto,
            caminho_audio=Path(destino).as_posix(),
            duracao_audio_segundos=duracao,
        )
    except Exception as erro:
        print(f"[erro] falha ao registrar o boletim no banco '{CAMINHO_DB}': {erro}")
        return 1

    # i) resumo final
    print(
        f"\nBoletim gerado com sucesso! ID: {id_boletim}, "
        f"Duracao: {duracao:.2f} segundos, Arquivo: {Path(destino).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
