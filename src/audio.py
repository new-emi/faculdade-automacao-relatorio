"""Modulo de saida de audio do pipeline "Boletim IA" (Output/TTS).

Recebe o roteiro em texto gerado por `src.boletim.gerar_boletim` e sintetiza a
narracao em pt-BR com o Kokoro (kokoro-onnx), salvando um WAV 16-bit PCM.

O Kokoro nao lida bem com textos longos (o roteiro costuma passar de 2000
caracteres), entao o texto e quebrado em chunks de no maximo MAX_CHARS
caracteres, respeitando limites de frase/palavra. Cada chunk vira um array
numpy; os arrays sao concatenados e gravados uma unica vez com soundfile.

Boletins gerados por LLM podem chegar com texto que o espeak-ng (fonemizador do
Kokoro) nao digere — caracteres de outros alfabetos (ex.: chines), colchetes e
marcadores como "[link]" — e nesses casos o modelo de voz entra em LOOP, repetindo
a mesma frase varias vezes no audio. Por isso existem duas protecoes:

 1. `_sanitizar_para_tts` limpa o texto antes de dividir em chunks (remove URLs,
    marcadores entre colchetes, simbolos soltos e qualquer caractere fora do
    alfabeto latino; expande %, $, & e @ para palavras; garante pontuacao final).
 2. `_sintetizar_trecho` verifica o audio gerado com `_repeticao` (auto-similaridade
    do espectro) e, ao detectar loop, re-sintetiza o trecho frase por frase.

Modelos usados (pasta models/, fora do git por serem > 100 MB):
    kokoro-v1.0.onnx, voices-v1.0.bin
Reconstruir com: python scripts/download_kokoro.py

Uso:
    from src.audio import sintetizar_audio
    caminho = sintetizar_audio(roteiro, "audio/boletim_<data>.wav")

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

# Deteccao de loop do TTS: se um trecho repetir a mesma fala, o espectro do audio
# fica periodicamente parecido consigo mesmo. Valores medidos num loop real:
# similaridade ~0,95 e periodo ~1,5 s.
LIMITE_REPETICAO = 0.90
PERIODO_MIN = 0.35  # segundos
PERIODO_MAX = 2.50  # segundos
JANELA_DETECCAO = 1.0  # segundos de audio comparados de uma vez

SAIDA_PADRAO = RAIZ / "audio" / "boletim_completo.wav"

# Marcacoes de markdown que nao devem ser lidas em voz alta.
_MARCADORES_MD = re.compile(r"(^|\s)[#>*_`~\-]+(\s|$)", re.MULTILINE)
_LINK_MD = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_SIMBOLOS_MD = re.compile(r"[*_`~#]+")
_FIM_DE_FRASE = re.compile(r"(?<=[.!?:;])\s+")
_ESPACOS = re.compile(r"\s+")

# Limpeza especifica para o TTS (ver docstring do modulo).
_URL = re.compile(r"(https?://\S+|www\.\S+)")
_MARCADOR_COLCHETE = re.compile(r"\[[^\]]*\]")
_NAO_LATINO = re.compile(r"[^A-Za-z0-9\s\.\,\;\:\!\?\(\)\"'\-\u00c0-\u00ff]")
_ESPACO_ANTES_PONTUACAO = re.compile(r"\s+([\.\,\;\:\!\?])")
_FIM_OK = re.compile(r"[\.\!\?]\s*$")


def _sanitizar_para_tts(texto: str) -> str:
    """Normaliza o texto para o espeak-ng/Kokoro ler sem travar.

    Remove URLs, links markdown, marcadores entre colchetes ("[link]", "[R]") e
    marcacoes de markdown; expande simbolos que o fonemizador le mal (%, $, &, @);
    descarta qualquer caractere fora do alfabeto latino (caracteres chineses,
    cirilicos, emoji) e garante que o trecho termine com pontuacao final.
    """
    texto = _URL.sub(" ", texto or "")
    texto = _LINK_MD.sub(r"\1", texto)  # mantem so o rotulo do link
    texto = _MARCADOR_COLCHETE.sub(" ", texto)
    texto = _SIMBOLOS_MD.sub(" ", texto)
    texto = _MARCADORES_MD.sub(" ", texto)
    texto = texto.replace("%", " por cento ")
    texto = texto.replace("&", " e ")
    texto = texto.replace("@", " arroba ")
    texto = re.sub(r"\$\s?(\d)", r"\1 dolares ", texto)
    texto = re.sub(r"(\d)\s?[Kk]\b", r"\1 mil ", texto)
    texto = re.sub(r"\bv(\d)", r"versao \1", texto)
    texto = _NAO_LATINO.sub(" ", texto)
    texto = _ESPACO_ANTES_PONTUACAO.sub(r"\1", texto)
    texto = _ESPACOS.sub(" ", texto).strip()
    if texto and not _FIM_OK.search(texto):
        texto += "."
    return texto


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

    texto = _sanitizar_para_tts(texto)
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


def _repeticao(amostras: np.ndarray, taxa: int) -> tuple[float, float]:
    """Mede auto-similaridade do audio para detectar loop do TTS.

    Compara o espectro de cada quadro com o de um quadro deslocado por um periodo
    candidato: se a similaridade media for alta com periodo curto, o trecho esta
    repetindo a mesma fala.

    Returns:
        (similaridade maxima, periodo em segundos). Similaridade 0.0 quando o
        trecho e curto demais para a analise.
    """
    tam_quadro = 1024
    salto = 256
    if amostras.size < tam_quadro * 8:
        return 0.0, 0.0

    total = 1 + (amostras.size - tam_quadro) // salto
    indices = np.arange(tam_quadro)[None, :] + salto * np.arange(total)[:, None]
    espectro = np.log1p(np.abs(np.fft.rfft(amostras[indices] * np.hanning(tam_quadro), axis=1)))
    espectro /= np.linalg.norm(espectro, axis=1, keepdims=True) + 1e-9

    janela = max(int(JANELA_DETECCAO * taxa / salto), 1)
    melhor_similaridade = 0.0
    melhor_periodo = 0.0
    for periodo in np.arange(PERIODO_MIN, PERIODO_MAX, 0.1):
        deslocamento = int(periodo * taxa / salto)
        if deslocamento < 1 or total - deslocamento < janela:
            continue
        similaridade = (espectro[:-deslocamento] * espectro[deslocamento:]).sum(axis=1)
        media = np.convolve(similaridade, np.ones(janela) / janela, mode="valid")
        pico = float(media.max())
        if pico > melhor_similaridade:
            melhor_similaridade, melhor_periodo = pico, float(periodo)
    return melhor_similaridade, melhor_periodo


def _gerar(kokoro: Kokoro, texto: str, voz: str, velocidade: float) -> tuple[np.ndarray, int]:
    """Sintetiza um texto e devolve (amostras float32, taxa de amostragem)."""
    amostras, taxa = kokoro.create(texto, voice=voz, speed=velocidade, lang=IDIOMA)
    return np.asarray(amostras, dtype=np.float32), int(taxa)


def _juntar_com_pausa(partes: list[np.ndarray], taxa: int) -> np.ndarray:
    """Concatena os pedacos de audio inserindo PAUSA_ENTRE_CHUNKS entre eles."""
    silencio = np.zeros(int(taxa * PAUSA_ENTRE_CHUNKS), dtype=np.float32)
    juntos: list[np.ndarray] = []
    for indice, parte in enumerate(partes):
        if indice:
            juntos.append(silencio)
        juntos.append(parte)
    return np.concatenate(juntos)


def _sintetizar_trecho(
    kokoro: Kokoro,
    texto: str,
    voz: str,
    velocidade: float,
) -> tuple[np.ndarray, int]:
    """Sintetiza um trecho verificando se o TTS entrou em loop.

    O Kokoro repete a mesma frase quando o espeak-ng nao fonemiza bem o texto. Ao
    detectar repeticao, o trecho e re-sintetizado frase por frase (concatenados com
    a mesma pausa dos chunks). Se uma frase isolada ainda repetir, um aviso e
    impresso e o audio dela e mantido: melhor um trecho impreciso do que perder a
    noticia do roteiro.

    Returns:
        (amostras float32, taxa de amostragem).
    """
    amostras, taxa = _gerar(kokoro, texto, voz, velocidade)
    similaridade, periodo = _repeticao(amostras, taxa)
    if similaridade < LIMITE_REPETICAO:
        return amostras, taxa

    print(
        f"  [aviso] repeticao detectada (similaridade {similaridade:.2f}, "
        f"periodo {periodo:.1f}s); re-sintetizando frase por frase."
    )
    frases = [frase.strip() for frase in _FIM_DE_FRASE.split(texto) if frase.strip()]
    if len(frases) < 2:
        print("  [aviso] trecho sem divisao possivel em frases; mantendo o audio original.")
        return amostras, taxa

    partes: list[np.ndarray] = []
    for frase in frases:
        sub, taxa_sub = _gerar(kokoro, frase, voz, velocidade)
        if taxa_sub != taxa:
            raise RuntimeError(
                f"taxa de amostragem inconsistente entre frases: {taxa} Hz e {taxa_sub} Hz."
            )
        similaridade_frase, periodo_frase = _repeticao(sub, taxa_sub)
        if similaridade_frase >= LIMITE_REPETICAO:
            print(
                f"  [aviso] frase ainda repetindo (similaridade {similaridade_frase:.2f}, "
                f"periodo {periodo_frase:.1f}s): {frase[:60]}..."
            )
        partes.append(sub)

    return _juntar_com_pausa(partes, taxa), taxa


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
        RuntimeError: se nenhum chunk gerar amostras de audio ou se a taxa de
            amostragem variar entre trechos.
    """
    chunks = dividir_em_chunks(texto)
    if not chunks:
        raise ValueError("texto vazio: nada para sintetizar.")

    kokoro = _carregar_kokoro()

    partes: list[np.ndarray] = []
    taxa_amostragem: int | None = None
    for indice, chunk in enumerate(chunks, start=1):
        print(f"  chunk {indice}/{len(chunks)} ({len(chunk)} chars): {chunk[:60]}...")
        amostras, taxa = _sintetizar_trecho(kokoro, chunk, voz, velocidade)
        if amostras.size == 0:
            continue
        if taxa_amostragem is None:
            taxa_amostragem = taxa
        elif taxa != taxa_amostragem:
            raise RuntimeError(
                f"taxa de amostragem inconsistente entre chunks: {taxa_amostragem} Hz "
                f"e {taxa} Hz."
            )
        partes.append(amostras)

    if not partes or taxa_amostragem is None:
        raise RuntimeError("nenhum chunk gerou audio (verifique os modelos do Kokoro).")

    audio = _juntar_com_pausa(partes, taxa_amostragem)

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
