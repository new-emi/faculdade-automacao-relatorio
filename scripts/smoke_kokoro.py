"""Smoke test do Kokoro TTS em pt-BR.

Carrega os modelos de models/, lista as vozes disponiveis (destacando as
de portugues), gera audio/smoke.wav e valida o arquivo resultante.

Uso (a partir da raiz do projeto):
    python scripts/smoke_kokoro.py
"""

from __future__ import annotations

import os
import sys

import soundfile as sf

from kokoro_onnx import Kokoro

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "models", "kokoro-v1.0.onnx")
VOICES_PATH = os.path.join(ROOT, "models", "voices-v1.0.bin")
AUDIO_DIR = os.path.join(ROOT, "audio")
OUT_PATH = os.path.join(AUDIO_DIR, "smoke.wav")

TEXT = "Boletim de IA. Teste de sintese de voz em portugues."
MIN_SIZE_BYTES = 5 * 1024

# Kokoro v1.0: 1o caractere do nome da voz = idioma, 2o = genero (f/m)
LANG_BY_PREFIX = {
    "a": "en-us",
    "b": "en-gb",
    "e": "es",
    "f": "fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt-br",
    "z": "cmn",
}


def voice_lang(voice: str) -> str:
    return LANG_BY_PREFIX.get(voice[:1], "?")


def main() -> int:
    for path in (MODEL_PATH, VOICES_PATH):
        if not os.path.exists(path):
            print(f"[erro] modelo ausente: {path}")
            print("       rode antes: python scripts/download_kokoro.py")
            return 1

    print(f"carregando modelos de {os.path.join(ROOT, 'models')} ...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)

    voices = sorted(kokoro.get_voices())
    print(f"\nvozes disponiveis ({len(voices)}):")
    for voice in voices:
        print(f"  {voice}  [{voice_lang(voice)}]")

    pt_voices = [v for v in voices if voice_lang(v) == "pt-br"]
    print(f"\nvozes pt-BR ({len(pt_voices)}): {', '.join(pt_voices) if pt_voices else 'nenhuma'}")
    if not pt_voices:
        print("[erro] nenhuma voz pt-BR encontrada em voices-v1.0.bin")
        return 1

    voice = pt_voices[0]
    print(f"\ngerando {OUT_PATH}\n  voz: {voice}\n  texto: {TEXT}")
    samples, sample_rate = kokoro.create(TEXT, voice=voice, speed=1.0, lang="pt-br")

    os.makedirs(AUDIO_DIR, exist_ok=True)
    sf.write(OUT_PATH, samples, sample_rate)

    size = os.path.getsize(OUT_PATH)
    duration = len(samples) / sample_rate
    print(f"  amostras: {len(samples)} | taxa: {sample_rate} Hz | duracao: {duration:.2f}s")

    if size <= MIN_SIZE_BYTES:
        print(f"[falha] {OUT_PATH} tem {size} bytes (esperado > {MIN_SIZE_BYTES})")
        return 1

    print(f"[ok] {OUT_PATH} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
