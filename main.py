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
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import soundfile as sf

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:  # garante "from src.*" mesmo rodando de outro cwd
    sys.path.insert(0, str(RAIZ))

from src.audio import sintetizar_audio
from src.boletim import gerar_boletim
from src.coletor import coletar_noticias
from src.registro import (
    concluir_execucao,
    inicializar_banco,
    iniciar_execucao,
    registrar_boletim,
    registrar_falha,
)

DIAS = 1
# 5 por fonte = ate 10 noticias por edicao; com 20 o modelo de 3B passou a omitir itens
# (ver README, limitacoes)
# Pode ser trocado sem editar o codigo pela variavel de ambiente BOLETIM_MAX_POR_FONTE
# (o servidor.py usa isso nos testes de carga: /gerar?max_por_fonte=N).
MAX_POR_FONTE = int(os.environ.get("BOLETIM_MAX_POR_FONTE", "5"))
CAMINHO_DB = "boletim.db"
PASTA_AUDIO = Path("audio")


def _agora() -> str:
    """Data/hora local no formato gravado no banco."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tempo(etapa: str, inicio: float) -> None:
    """Imprime o tempo gasto numa etapa num formato fixo, lido pelo servidor.py.

    Exemplo de linha: "[tempo] roteiro 152.31". O servidor procura essas linhas no
    stdout e grava os segundos de cada etapa na tabela `requisicoes` do banco.
    """
    print(f"[tempo] {etapa} {time.perf_counter() - inicio:.2f}", flush=True)


def _registrar_falha(id_execucao: int, etapa: str, mensagem: str) -> None:
    """Grava a falha na tabela `execucoes` sem esconder o erro que parou o pipeline."""
    try:
        registrar_falha(CAMINHO_DB, id_execucao, etapa=etapa, mensagem=mensagem)
    except Exception as erro:
        print(f"[aviso] falha ao registrar a execucao id={id_execucao} no banco: {erro}")


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

    # a2) auditoria da execucao (tabela `execucoes`, separada de `boletins`)
    try:
        id_execucao = iniciar_execucao(CAMINHO_DB, carimbo)
    except Exception as erro:
        print(f"[erro] nao foi possivel registrar o inicio da execucao: {erro}")
        return 1

    print(f"Execucao id={id_execucao} aberta na tabela 'execucoes'.")

    # b) coleta
    print(f"\n[1/4] Coletando noticias (ultimos {DIAS} dia(s), ate {MAX_POR_FONTE} por fonte)...")
    t0 = time.perf_counter()
    try:
        noticias = coletar_noticias(dias=DIAS, max_por_fonte=MAX_POR_FONTE)
    except Exception as erro:
        print(f"[erro] falha na coleta de noticias: {erro}")
        _registrar_falha(id_execucao, "coleta", str(erro))
        return 1

    # c) sem noticias: encerra sem gerar boletim
    if not noticias:
        aviso = (
            f"nenhuma noticia coletada nos ultimos {DIAS} dia(s); "
            "encerrando sem gerar boletim (verifique a conexao de rede)."
        )
        print(f"[aviso] {aviso}")
        _registrar_falha(id_execucao, "coleta", aviso)
        return 1
    _tempo("coleta", t0)

    print(f"{len(noticias)} noticias coletadas.")

    # d) roteiro via LLM
    print("\n[2/4] Gerando o roteiro com o LLM local (qwen2.5:3b)...")
    t0 = time.perf_counter()
    try:
        texto = gerar_boletim(noticias)
    except Exception as erro:
        print(f"[erro] falha ao gerar o roteiro do boletim: {erro}")
        _registrar_falha(id_execucao, "roteiro", str(erro))
        return 1
    _tempo("roteiro", t0)

    print(f"Roteiro pronto ({len(texto)} caracteres).")

    # e/f) TTS -> WAV
    print(f"\n[3/4] Sintetizando o audio em '{caminho_audio.as_posix()}'...")
    t0 = time.perf_counter()
    try:
        destino = sintetizar_audio(texto, caminho_audio.as_posix())
    except Exception as erro:
        print(f"[erro] falha ao sintetizar o audio: {erro}")
        _registrar_falha(id_execucao, "audio", str(erro))
        return 1

    # g) duracao real do WAV gravado
    try:
        amostras, taxa_amostragem = sf.read(str(destino))
        duracao = len(amostras) / float(taxa_amostragem)
    except Exception as erro:
        print(f"[erro] falha ao ler o WAV gerado em '{destino}': {erro}")
        _registrar_falha(id_execucao, "leitura_wav", str(erro))
        return 1
    _tempo("audio", t0)

    # h) registro no SQLite
    print(f"\n[4/4] Registrando o boletim em '{CAMINHO_DB}'...")
    t0 = time.perf_counter()
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
        _registrar_falha(id_execucao, "registro", str(erro))
        return 1
    _tempo("registro", t0)

    # i) fecha a execucao como sucesso, ligada ao boletim gravado
    try:
        concluir_execucao(
            CAMINHO_DB,
            id_execucao,
            id_boletim=id_boletim,
            qtd_noticias=len(noticias),
            data_fim=_agora(),
        )
    except Exception as erro:
        print(
            f"[aviso] boletim id={id_boletim} gravado, mas a execucao id={id_execucao} "
            f"nao foi finalizada no banco: {erro}"
        )

    # j) resumo final
    print(
        f"\nBoletim gerado com sucesso! ID: {id_boletim}, "
        f"Duracao: {duracao:.2f} segundos, Arquivo: {Path(destino).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
