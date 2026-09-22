"""Verificacao da revisao de idioma/despedida dos trechos do roteiro (src/boletim.py).

Roda sem Ollama e sem rede: usa apenas a heuristica de marcadores de `src.boletim` e os
roteiros ja gravados em boletim.db, mais um LLM falso para exercitar a retentativa.

Uso (a partir da raiz do projeto):
    python scripts/verifica_idioma.py
"""

from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import src.boletim as boletim
from src.boletim import _contar_marcadores, _revisar_trecho, _tem_despedida, parece_portugues

CAMINHO_DB = RAIZ / "boletim.db"

TRECHO_EM_INGLES = (
    "Ivan did some benchmarks comparing different language models. His results show that "
    "the approach has notably lower gaps than the others in this benchmark set."
)
TRECHO_EM_PORTUGUES = (
    "Hoje falamos sobre um estudo de benchmarks que compara modelos de linguagem e mostra "
    "que uma das abordagens erra menos quando o assunto e incerteza."
)
NOTICIAS_FALSAS = [{"fonte": "HN", "titulo": "titulo", "url": "url", "texto_base": ""}]


def _roteiros() -> list[tuple[int, str, str]]:
    """Le (id, data_geracao, texto_boletim) de boletim.db, do mais antigo ao mais novo."""
    if not CAMINHO_DB.exists():
        raise SystemExit(f"banco nao encontrado: {CAMINHO_DB}. Rode antes: python main.py")
    return sqlite3.connect(CAMINHO_DB).execute(
        "SELECT id, data_geracao, texto_boletim FROM boletins ORDER BY id"
    ).fetchall()


def verificar_roteiros() -> None:
    """Mostra o veredito da heuristica para cada roteiro gravado no banco."""
    print("== Roteiros gravados em boletim.db ==")
    for id_boletim, data, texto in _roteiros():
        portugues, ingles = _contar_marcadores(texto)
        print(
            f"  id={id_boletim:<3} {data}  chars={len(texto):<5} "
            f"marcadores pt={portugues:<4} en={ingles:<3} "
            f"portugues={parece_portugues(texto)!s:<5} problemas={_revisar_trecho(texto, True)}"
        )


def verificar_paragrafos() -> None:
    """Lista os paragrafos que a revisao reprovaria, como medida de falso positivo.

    Num roteiro em portugues nenhum paragrafo deveria ser reprovado: cada reprovacao aqui
    e um paragrafo realmente escrito em ingles ou uma despedida fora do ultimo trecho.
    """
    print("\n== Paragrafos reprovados no conjunto dos roteiros ==")
    total = reprovados = 0
    for id_boletim, _, texto in _roteiros():
        for numero, paragrafo in enumerate(texto.split("\n\n"), start=1):
            total += 1
            problemas = _revisar_trecho(paragrafo, ultimo=False)
            if not problemas:
                continue
            reprovados += 1
            portugues, ingles = _contar_marcadores(paragrafo)
            print(
                f"  id={id_boletim} paragrafo {numero} (pt={portugues}, en={ingles}, "
                f"despedida={_tem_despedida(paragrafo)}): {'; '.join(problemas)}"
            )
    print(f"  {reprovados} reprovado(s) em {total} paragrafo(s).")


def verificar_retentativa() -> None:
    """Exercita `_gerar_trecho` com um LLM falso: ingles na 1a resposta, portugues na 2a."""
    print("\n== Retentativa de trecho (LLM falso, sem rede) ==")
    respostas = iter([TRECHO_EM_INGLES, TRECHO_EM_PORTUGUES])
    chamadas: list[list[dict]] = []

    def llm_falso(mensagens: list[dict]) -> str:
        chamadas.append(mensagens)
        return next(respostas)

    original = boletim._chamar_ollama
    boletim._chamar_ollama = llm_falso
    try:
        trecho = boletim._gerar_trecho(NOTICIAS_FALSAS, 1, 1)
    finally:
        boletim._chamar_ollama = original

    print(f"  chamadas ao LLM: {len(chamadas)} (esperado 2)")
    print(f"  correcao pedida ao modelo: {chamadas[-1][-1]['content'][:70]}...")
    print(f"  trecho aprovado: {not _revisar_trecho(trecho, ultimo=True)}")


def verificar_desistencia() -> bool:
    """Confirma que `_gerar_trecho` falha (em vez de gravar audio em ingles) se persistir."""
    print("\n== Desistencia com erro claro se o ingles persistir ==")
    original = boletim._chamar_ollama
    boletim._chamar_ollama = lambda mensagens: TRECHO_EM_INGLES
    try:
        boletim._gerar_trecho(NOTICIAS_FALSAS, 1, 1)
    except RuntimeError as erro:
        print(f"  RuntimeError levantado como esperado: {str(erro)[:70]}...")
        return True
    finally:
        boletim._chamar_ollama = original
    print("  FALHA: deveria ter levantado RuntimeError")
    return False


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):  # console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    verificar_roteiros()
    verificar_paragrafos()
    verificar_retentativa()
    if not verificar_desistencia():
        return 1

    print("\n[ok] verificacao concluida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
