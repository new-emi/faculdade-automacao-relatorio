"""Baixa os modelos do Kokoro (kokoro-onnx) para models/.

Fontes, na ordem: HuggingFace (URLs originais do projeto) e, como fallback,
as releases oficiais do GitHub (mesmos arquivos, mesmos nomes).
A URL do HuggingFace responde 401 para acesso anonimo, por isso o fallback.

Reiniciavel: se o arquivo final ja existe com o tamanho esperado, pula.
Se existe parcial, retoma via Range; se o servidor nao suportar Range,
recomeca do zero.

Uso (a partir da raiz do projeto):
    python scripts/download_kokoro.py
"""

from __future__ import annotations

import os
import shutil
import sys

import requests

HF = "https://huggingface.co/thewh1teagle/kokoro-onnx/resolve/main/model_files"
GH = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"

MODELS = [
    {
        "name": "kokoro-v1.0.onnx",
        "size": 325_505_369,
        "urls": [f"{HF}/kokoro-v1.0.onnx", f"{GH}/kokoro-v1.0.onnx"],
    },
    {
        "name": "voices-v1.0.bin",
        "size": 28_214_398,
        "urls": [f"{HF}/voices-v1.0.bin", f"{GH}/voices-v1.0.bin"],
    },
]

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
CHUNK_SIZE = 1024 * 1024  # 1 MB
PROGRESS_EVERY = 10 * 1024 * 1024  # reporta a cada 10 MB


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fetch_to(url: str, entry: dict) -> bool:
    """Baixa uma URL para <dest>.part. Retorna True se o arquivo ficou completo."""
    dest = os.path.join(MODELS_DIR, entry["name"])
    expected = entry["size"]
    resume_from = os.path.getsize(dest) if os.path.exists(dest) else 0
    tmp = dest + ".part"

    # o .part de uma tentativa anterior tem prioridade sobre o arquivo final truncado
    if os.path.exists(tmp):
        resume_from = max(resume_from, os.path.getsize(tmp))
    if resume_from > expected:
        resume_from = 0

    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    if resume_from:
        print(f"  retomando de {human(resume_from)}")

    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            if resume_from and r.status_code != 206:
                print("  servidor nao suporta retomada; reiniciando do zero")
                resume_from = 0
                headers = {}
            r.raise_for_status()

            mode = "ab" if resume_from else "wb"
            downloaded = resume_from
            next_report = downloaded + PROGRESS_EVERY
            with open(tmp, mode) as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        pct = downloaded * 100 / expected
                        print(f"  {entry['name']}: {human(downloaded)} ({pct:.1f}%)")
                        next_report = downloaded + PROGRESS_EVERY
    except (requests.RequestException, OSError) as exc:
        partial = human(os.path.getsize(tmp)) if os.path.exists(tmp) else "nada"
        print(f"  falhou: {exc} (parcial: {partial})")
        return False

    actual = os.path.getsize(tmp)
    if actual != expected:
        print(f"  incompleto: {human(actual)} de {human(expected)} (parcial mantido em .part)")
        return False

    if os.path.exists(dest):
        os.remove(dest)
    shutil.move(tmp, dest)
    print(f"  [ok] {entry['name']} -> {human(actual)}")
    return True


def download(entry: dict) -> bool:
    dest = os.path.join(MODELS_DIR, entry["name"])
    if os.path.exists(dest) and os.path.getsize(dest) == entry["size"]:
        print(f"[skip] {entry['name']} ja completo ({human(entry['size'])})")
        return True

    print(f"[baixando] {entry['name']} ({human(entry['size'])})")
    for url in entry["urls"]:
        print(f"  fonte: {url}")
        if fetch_to(url, entry):
            return True

    print(f"[falha] {entry['name']} nao foi baixado por nenhuma fonte")
    return False


def main() -> int:
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"destino: {MODELS_DIR}")
    failed = [e["name"] for e in MODELS if not download(e)]

    if failed:
        print(f"[falha] modelos ausentes: {', '.join(failed)}")
        return 1
    print("[concluido] todos os modelos presentes em models/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
