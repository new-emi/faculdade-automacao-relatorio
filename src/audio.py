"""Modulo de saida de audio do pipeline "Boletim IA" (Output/TTS).

Recebe o roteiro em texto gerado por `src.boletim.gerar_boletim` e sintetiza a
narracao em pt-BR com o Kokoro (kokoro-onnx), salvando um WAV 16-bit PCM.

O Kokoro nao lida bem com textos longos (o roteiro costuma passar de 2000
caracteres), entao o texto e quebrado em chunks de no maximo MAX_CHARS
caracteres, respeitando limites de frase/palavra. Cada chunk vira um array
numpy; os arrays sao concatenados e gravados uma unica vez com soundfile.

Modelos usados (pasta models/, fora do git por serem > 100 MB):
    kokoro-v1.0.onnx, voices-v1.0.bin
Reconstruir com: python scripts/download_kokoro.py

Uso:
    from src.audio import sintetizar_audio
    caminho = sintetizar_audio(roteiro, "audio/boletim_completo.wav")

Teste rapido (a partir da raiz do projeto, com o Ollama ativo):
    python src/audio.py
"""

from __future__ import annotations

import io
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

RAIZ = Path(__file__).resolve().parents[1]
MODELO_KOKORO = RAIZ / "models" / "kokoro-v1.0.onnx"
VOZES_KOKORO = RAIZ / "models" / "voices-v1.0.bin"

VOZ = "pf_dora"  # voz pt-BR validada na sessao 1 (convencao Kokoro: p=pt-br, f=feminino)
IDIOMA = "pt-br"
VELOCIDADE = 1.0

# Acima disso o Kokoro falha/piora muito a prosodia: quebramos o roteiro em chunks.
MAX_CHARS = 400
PAUSA_ENTRE_CHUNKS = 0.12  # segundos de silencio entre chunks, para a fala nao "colar"

SAIDA_PADRAO = RAIZ / "audio" / "boletim_completo.wav"

# Marcacoes de markdown que nao devem ser lidas em voz alta.
_MARCADORES_MD = re.compile(r"(^|\s)[#>*_`~\-]+(\s|$)", re.MULTILINE)
_LINK_MD = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_SIMBOLOS_MD = re.compile(r"[*_`~#]+")
_FIM_DE_FRASE = re.compile(r"(?<=[.!?:;])\s+")
_ESPACOS = re.compile(r"\s+")


def _limpar_texto(texto: str) -> str:
    """Normaliza espacos e remove marcacoes de markdown, que o TTS nao deve ler."""
    texto = _LINK_MD.sub(r"\1", texto or "")  # mantem so o rotulo do link
    texto = _SIMBOLOS_MD.sub(" ", texto)
    texto = _MARCADORES_MD.sub(" ", texto)
    return _ESPACOS.sub(" ", texto).strip()


def _quebrar_frase_longa(frase: str, limite: int) -> list[str]:
    """Quebra uma unica frase maior que `limite` em pedacos por limite de palavra."""
    pedacos: list[str] = []
    atual = ""
    for palavra in frase.split():
        if len(palavra) > limite:  # caso extremo (URL gigante): corta na forca
            if atual:
                pedacos.append(atual)
                atual = ""
            pedacos.extend(palavra[i : i + limite] for i in range(0, len(palavra), limite))
            continue
        if not atual:
            atual = palavra
        elif len(atual) + 1 + len(palavra) <= limite:
            atual = f"{atual} {palavra}"
        else:
            pedacos.append(atual)
            atual = palavra
    if atual:
        pedacos.append(atual)
    return pedacos


def dividir_em_chunks(texto: str, limite: int = MAX_CHARS) -> list[str]:
    """Divide o texto em chunks de no maximo `limite` caracteres.

    Agrupa frases inteiras enquanto couberem; frases maiores que o limite sao
    quebradas por palavra. Nunca retorna chunk vazio nem acima do limite.
    """
    if limite < 1:
        raise ValueError("limite precisa ser >= 1 caractere.")

    texto = _limpar_texto(texto)
    if not texto:
        return []

    chunks: list[str] = []
    atual = ""
    for frase in _FIM_DE_FRASE.split(texto):
        frase = frase.strip()
        if not frase:
            continue

        for pedaco in (
            [frase] if len(frase) <= limite else _quebrar_frase_longa(frase, limite)
        ):
            if not atual:
                atual = pedaco
            elif len(atual) + 1 + len(pedaco) <= limite:
                atual = f"{atual} {pedaco}"
            else:
                chunks.append(atual)
                atual = pedaco
    if atual:
        chunks.append(atual)

    return chunks


@lru_cache(maxsize=1)
def _carregar_kokoro() -> Kokoro:
    """Carrega o modelo Kokoro uma unica vez por processo (o load leva alguns segundos)."""
    for caminho in (MODELO_KOKORO, VOZES_KOKORO):
        if not caminho.exists():
            raise FileNotFoundError(
                f"modelo ausente: {caminho}. Rode antes: python scripts/download_kokoro.py"
            )
    return Kokoro(str(MODELO_KOKORO), str(VOZES_KOKORO))


def sintetizar_audio(
    texto: str,
    caminho_saida: str,
    voz: str = VOZ,
    velocidade: float = VELOCIDADE,
) -> Path:
    """Sintetiza `texto` em pt-BR e grava um WAV 16-bit PCM em `caminho_saida`.

    Args:
        texto: roteiro a ser narrado (markdown e tolerado; a formatacao e removida).
        caminho_saida: destino do WAV (pastas sao criadas se necessario).
        voz: voz Kokoro (padrao pf_dora, pt-BR feminina).
        velocidade: fator de velocidade da fala.

    Returns:
        Path do arquivo WAV gravado.

    Raises:
        ValueError: se o texto nao tiver conteudo narravel.
        FileNotFoundError: se os modelos Kokoro nao estiverem em models/.
        RuntimeError: se nenhum chunk gerar amostras de audio.
    """
    chunks = dividir_em_chunks(texto)
    if not chunks:
        raise ValueError("texto vazio: nada para sintetizar.")

    kokoro = _carregar_kokoro()

    partes: list[np.ndarray] = []
    taxa_amostragem: int | None = None
    for indice, chunk in enumerate(chunks, start=1):
        print(f"  chunk {indice}/{len(chunks)} ({len(chunk)} chars): {chunk[:60]}...")
        amostras, taxa = kokoro.create(chunk, voice=voz, speed=velocidade, lang=IDIOMA)
        amostras = np.asarray(amostras, dtype=np.float32)
        if amostras.size == 0:
            continue
        if taxa_amostragem is None:
            taxa_amostragem = int(taxa)
        elif int(taxa) != taxa_amostragem:
            raise RuntimeError(
                f"taxa de amostragem inconsistente entre chunks: {taxa_amostragem} Hz "
                f"e {taxa} Hz."
            )
        partes.append(amostras)

    if not partes or taxa_amostragem is None:
        raise RuntimeError("nenhum chunk gerou audio (verifique os modelos do Kokoro).")

    silencio = np.zeros(int(taxa_amostragem * PAUSA_ENTRE_CHUNKS), dtype=np.float32)
    intermediarios = []
    for i, parte in enumerate(partes):
        if i:
            intermediarios.append(silencio)
        intermediarios.append(parte)
    audio = np.concatenate(intermediarios)

    destino = Path(caminho_saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destino), audio, taxa_amostragem, subtype="PCM_16")
    return destino


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Permite rodar tanto "python src/audio.py" quanto "python -m src.audio".
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from src.boletim import gerar_boletim, salvar_boletim
    from src.coletor import coletar_noticias

    QTD_NOTICIAS = 3
    MIN_BYTES = 500 * 1024  # 500 KB

    coletadas = coletar_noticias(dias=2, max_por_fonte=QTD_NOTICIAS)
    noticias = coletadas[:QTD_NOTICIAS]
    if not noticias:
        print("[erro] nenhuma noticia coletada; abortando.")
        sys.exit(1)

    print(f"\n{len(noticias)} de {len(coletadas)} noticias selecionadas. Gerando roteiro...")
    roteiro = gerar_boletim(noticias)
    salvar_boletim(roteiro, Path("output") / "boletim_texto.md")

    print("-" * 70)
    print(roteiro)
    print("-" * 70)

    print(f"\nSintetizando com Kokoro (voz {VOZ}, chunks de ate {MAX_CHARS} chars)...")
    destino = sintetizar_audio(roteiro, str(SAIDA_PADRAO))

    tamanho = destino.stat().st_size
    info = sf.info(str(destino))
    print(
        f"\n[ok] {destino} | {tamanho} bytes ({tamanho / 1024:.1f} KB) | "
        f"{info.frames} amostras | {info.samplerate} Hz | "
        f"{info.subtype} | {info.duration:.2f}s"
    )

    if tamanho <= MIN_BYTES:
        print(f"[falha] arquivo menor que o esperado ({MIN_BYTES} bytes).")
        sys.exit(1)
    if info.frames == 0:
        print("[falha] arquivo sem amostras (audio corrompido).")
        sys.exit(1)

    print(f"[ok] audio valido: {info.duration / 60:.2f} min de narracao.")
