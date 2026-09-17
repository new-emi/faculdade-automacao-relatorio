"""Modulo de processamento do pipeline "Boletim IA" (Process).

Recebe a lista de noticias normalizada pelo coletor (Input) e usa o LLM local
servido pelo Ollama para escrever o roteiro do boletim em pt-BR.

O LLM trabalha APENAS com o que o coletor entregou (fonte, titulo, url e
texto_base). Este modulo NAO faz scraping das URLs originais.

Cada noticia deve ser um dicionario com as chaves:
    fonte, titulo, url, texto_base, data_publicacao, score

Uso:
    from src.coletor import coletar_noticias
    from src.boletim import gerar_boletim

    noticias = coletar_noticias(dias=3, max_por_fonte=5)
    roteiro = gerar_boletim(noticias)

Teste rapido (a partir da raiz do projeto, com o Ollama ativo):
    python src/boletim.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import requests

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODELO = "qwen2.5:3b"
TEMPERATURA = 0.6  # baixa o suficiente para nao inventar fatos, alta o suficiente para nao repetir

# (conexao, leitura) em segundos: um LLM local de 3B pode levar minutos para gerar o roteiro.
TIMEOUT_LLM = (10, 600)

SAIDA_PADRAO = Path("output/boletim_texto.md")

PROMPT_SISTEMA = (
    "Voce e o ancora do 'Boletim IA', um podcast/relatorio diario sobre o mercado de "
    "Inteligencia Artificial. Seu tom e profissional, dinamico, claro e em PT-BR. Voce deve "
    "criar um roteiro fluido para ser lido em voz alta: faca uma introducao curta, agrupe as "
    "noticias por temas (ex: LLMs, Agentes, Mercado, Pesquisas) e cite os titulos de forma "
    "natural, sem apenas ler uma lista robolica. Termine com uma conclusao breve. "
    "REGRA CRITICA: NUNCA invente fatos, nomes de empresas, detalhes tecnicos ou "
    "desdobramentos que nao estejam explicitos no titulo ou no texto_base fornecido. Se o "
    "texto_base for curto ou vazio, limite-se a apresentar o titulo e dizer que o tema esta "
    "em discussao no mercado, sem especular detalhes. Nao invente significados para siglas."
)


def _formatar_noticias(noticias: list[dict]) -> str:
    """Monta a lista de noticias no formato 'Fonte | Titulo | URL | Texto Base'."""
    linhas = []
    for indice, noticia in enumerate(noticias, start=1):
        texto_base = " ".join((noticia.get("texto_base") or "").split()) or "(sem texto base)"
        titulo = " ".join((noticia.get("titulo") or "").split()) or "(sem titulo)"
        linhas.append(
            f"{indice}. {noticia.get('fonte') or 'desconhecida'} | {titulo} | "
            f"{noticia.get('url') or '(sem url)'} | {texto_base}"
        )
    return "\n".join(linhas)


def _montar_prompt_usuario(noticias: list[dict]) -> str:
    """Monta a mensagem de usuario com as noticias disponiveis para o roteiro."""
    return (
        f"Noticias disponiveis hoje ({len(noticias)}), no formato "
        "'Fonte | Titulo | URL | Texto Base':\n\n"
        f"{_formatar_noticias(noticias)}\n\n"
        "Escreva o roteiro do Boletim IA de hoje usando apenas as informacoes acima. "
        "Nao invente fatos, numeros ou citacoes que nao estejam no material."
    )


def gerar_boletim(noticias: list[dict]) -> str:
    """Gera o roteiro do boletim em pt-BR a partir das noticias coletadas.

    Args:
        noticias: lista de dicts normalizados pelo coletor (fonte, titulo, url,
            texto_base, data_publicacao, score).

    Returns:
        Texto do roteiro em markdown, pronto para ser lido em voz alta.

    Raises:
        ValueError: se a lista de noticias estiver vazia.
        RuntimeError: se o Ollama estiver inacessivel ou responder em formato inesperado.
    """
    noticias = list(noticias or [])
    if not noticias:
        raise ValueError("nenhuma noticia recebida: nada para o LLM processar.")

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": _montar_prompt_usuario(noticias)},
        ],
        "stream": False,
        "options": {"temperature": TEMPERATURA},
    }

    try:
        resposta = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=TIMEOUT_LLM)
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise RuntimeError(
            f"falha ao chamar o Ollama em {OLLAMA_CHAT_URL}: {erro}. "
            "Verifique se o servico esta ativo ('ollama list') e se o modelo "
            f"'{MODELO}' esta baixado ('ollama pull {MODELO}')."
        ) from erro

    try:
        corpo = resposta.json()
    except ValueError as erro:
        raise RuntimeError(f"Ollama retornou resposta que nao e JSON: {erro}") from erro

    if corpo.get("error"):
        raise RuntimeError(f"Ollama retornou erro: {corpo['error']}")

    texto = (corpo.get("message") or {}).get("content") or ""
    texto = texto.strip()
    if not texto:
        raise RuntimeError(f"Ollama nao retornou texto (resposta: {corpo!r}).")

    return texto


def salvar_boletim(texto: str, caminho: Path = SAIDA_PADRAO) -> Path:
    """Grava o roteiro em markdown no caminho indicado, criando as pastas necessarias."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto + "\n", encoding="utf-8")
    return caminho


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Permite rodar tanto "python src/boletim.py" quanto "python -m src.boletim".
    raiz = Path(__file__).resolve().parents[1]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from src.coletor import coletar_noticias

    coletadas = coletar_noticias(dias=2, max_por_fonte=3)
    print(f"\n{len(coletadas)} noticias coletadas. Gerando o boletim com {MODELO}...")

    if not coletadas:
        print("nenhuma noticia coletada; abortando a geracao do boletim.")
        sys.exit(1)

    roteiro = gerar_boletim(coletadas)
    destino = salvar_boletim(roteiro, Path("output") / "boletim_texto.md")

    print(f"\nBoletim salvo em: {destino} ({len(roteiro)} caracteres)\n")
    print("-" * 70)
    print(roteiro)
    print("-" * 70)
    print(f"\n[ok] boletim gerado a partir de {len(coletadas)} noticias.")
