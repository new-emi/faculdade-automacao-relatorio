"""Modulo de coleta de noticias de IA (Input do pipeline "Boletim IA").

Consome duas fontes publicas que NAO exigem chave de API:

    A) Hacker News via Algolia Search API (search_by_date)
       https://hn.algolia.com/api/v1/search_by_date
    B) Reddit, com UMA rota publica (Atom):
       https://www.reddit.com/r/<sub>/new/.rss
       Subreddits: r/MachineLearning e r/artificial.
       O acesso anonimo ao Reddit tem rate limit baixo (1 req/min por IP),
       entao a rota Atom espera REDDIT_ESPERA_429 s quando recebe HTTP 429.

A rota JSON (r/<sub>/new.json) foi testada nesta rede e responde HTTP 403
(bloqueio por IP, com qualquer User-Agent) em todas as execucoes. Ela foi
REMOVIDA do codigo para nao gastar uma requisicao por subreddit nem poluir o
log com avisos de uma rota que nunca funciona.

Cada noticia e normalizada num dicionario com as chaves:
    fonte, titulo, url, texto_base, data_publicacao, score

Observacao sobre o score do Reddit: o feed Atom nao expoe upvotes, entao nos
itens do Reddit o campo score vem 0 (a chave e mantida por uniformidade do
dicionario).

Uso:
    from src.coletor import coletar_noticias
    noticias = coletar_noticias(dias=3, max_por_fonte=5)

Teste rapido (a partir da raiz do projeto):
    python src/coletor.py
"""

from __future__ import annotations

import html
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_TERMOS = ("AI", "LLM", "Artificial Intelligence")

REDDIT_SUBREDDITS = ("MachineLearning", "artificial")
REDDIT_RSS_TEMPLATE = "https://www.reddit.com/r/{sub}/new/.rss"
REDDIT_ESPERA_429 = 60  # segundos de espera apos HTTP 429 (x-ratelimit-reset)
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Reddit bloqueia User-Agent generico/padrao do requests.
USER_AGENT = "Mozilla/5.0 AI-Factory-Bot/1.0"

REQUEST_TIMEOUT = 15  # segundos por requisicao
LIMITE_TEXTO = 500  # tamanho maximo de texto_base, para nao estourar o contexto do LLM

_TAGS_HTML = re.compile(r"<[^>]+>")
_COMENTARIOS_HTML = re.compile(r"<!--.*?-->", re.DOTALL)


def _headers() -> dict:
    return {"User-Agent": USER_AGENT}


def _iso_utc(timestamp: float) -> str:
    """Converte epoch (segundos) em ISO 8601 com timezone UTC."""
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()


def _epoch_iso(texto: str) -> float:
    """Converte uma data ISO 8601 (ex.: 2026-09-16T23:20:58+00:00) em epoch."""
    return datetime.fromisoformat(texto).timestamp()


def _truncar(texto: str, limite: int = LIMITE_TEXTO) -> str:
    """Normaliza espacos e trunca o texto em ~limite chars."""
    texto = " ".join((texto or "").split())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3].rstrip() + "..."


def _html_para_texto(bruto: str) -> str:
    """Remove comentarios/tags HTML do conteudo do feed Atom."""
    texto = _COMENTARIOS_HTML.sub(" ", bruto or "")
    texto = _TAGS_HTML.sub(" ", texto)
    return html.unescape(texto)


def _coletar_hn(dias: int, max_por_fonte: int) -> list[dict]:
    """Historias do Hacker News (tags=story) das ultimas `dias` dias."""
    inicio = int(time.time()) - dias * 86400
    vistas: set[str] = set()
    noticias: list[dict] = []

    for termo in HN_TERMOS:
        if len(noticias) >= max_por_fonte:
            break

        params = {
            "query": termo,
            "tags": "story",
            "numericFilters": f"created_at_i>{inicio}",
            "hitsPerPage": max_por_fonte,
        }
        try:
            resposta = requests.get(
                HN_SEARCH_URL, params=params, headers=_headers(), timeout=REQUEST_TIMEOUT
            )
            resposta.raise_for_status()
            hits = resposta.json().get("hits", [])
        except requests.RequestException as erro:
            print(f"[aviso] HN Algolia falhou para '{termo}': {erro}")
            continue
        except ValueError as erro:  # JSON invalido / corpo inesperado
            print(f"[aviso] HN Algolia retornou resposta invalida para '{termo}': {erro}")
            continue

        for hit in hits:
            if len(noticias) >= max_por_fonte:
                break

            object_id = str(hit.get("objectID") or "")
            if object_id and object_id in vistas:
                continue
            vistas.add(object_id)

            item_url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            criado_em = hit.get("created_at")
            if not criado_em:
                criado_em = _iso_utc(hit.get("created_at_i") or time.time())

            noticias.append(
                {
                    "fonte": "HN",
                    "titulo": _truncar(hit.get("title") or "", 300),
                    "url": item_url,
                    "texto_base": _truncar(hit.get("story_text") or ""),
                    "data_publicacao": criado_em,
                    "score": int(hit.get("points") or 0),
                }
            )

    return noticias


def _posts_via_rss(sub: str) -> list[dict]:
    """Posts recentes do subreddit pelo feed Atom publico.

    Se o Reddit responder 429 (rate limit anonimo), espera REDDIT_ESPERA_429 s
    e faz uma unica nova tentativa.
    """
    url = REDDIT_RSS_TEMPLATE.format(sub=sub)
    resposta = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    if resposta.status_code == 429:
        print(
            f"[aviso] Reddit r/{sub} respondeu 429 (rate limit); "
            f"aguardando {REDDIT_ESPERA_429}s antes de tentar de novo."
        )
        time.sleep(REDDIT_ESPERA_429)
        resposta = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)

    resposta.raise_for_status()
    raiz = ET.fromstring(resposta.content)

    itens = []
    for entry in raiz.findall("atom:entry", ATOM_NS):
        link = entry.find("atom:link", ATOM_NS)
        link_url = (link.get("href") if link is not None else "") or ""
        publicado = (entry.findtext("atom:published", default="", namespaces=ATOM_NS) or "").strip()
        try:
            epoch = _epoch_iso(publicado) if publicado else 0.0
        except ValueError:
            epoch = 0.0
        itens.append(
            {
                "id": (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or link_url).strip(),
                "titulo": entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "",
                "url": link_url,
                "texto": _html_para_texto(entry.findtext("atom:content", default="", namespaces=ATOM_NS)),
                "data_publicacao": publicado,
                "epoch": epoch,
                "score": 0,  # o feed Atom nao expoe upvotes
            }
        )
    return itens


def _posts_reddit(sub: str) -> list[dict]:
    """Posts recentes do subreddit pelo feed Atom publico (unica rota anonima disponivel)."""
    try:
        return _posts_via_rss(sub)
    except (requests.RequestException, ValueError, ET.ParseError) as erro:
        print(f"[aviso] Reddit r/{sub} via RSS falhou: {erro}")
        return []


def _coletar_reddit(dias: int, max_por_fonte: int) -> list[dict]:
    """Posts recentes dos subreddits de IA, dentro da janela de `dias`."""
    corte = time.time() - dias * 86400
    vistas: set[str] = set()
    noticias: list[dict] = []

    for sub in REDDIT_SUBREDDITS:
        if len(noticias) >= max_por_fonte:
            break

        for post in _posts_reddit(sub):
            if len(noticias) >= max_por_fonte:
                break
            if not post["epoch"] or post["epoch"] < corte:
                continue
            if post["id"] in vistas:
                continue
            vistas.add(post["id"])

            noticias.append(
                {
                    "fonte": "Reddit",
                    "titulo": _truncar(post["titulo"], 300),
                    "url": post["url"],
                    "texto_base": _truncar(post["texto"]),
                    "data_publicacao": post["data_publicacao"],
                    "score": post["score"],
                }
            )

    return noticias


def coletar_noticias(dias: int = 1, max_por_fonte: int = 10) -> list[dict]:
    """Coleta noticias de IA no Hacker News e no Reddit.

    Args:
        dias: janela de tempo em dias (publicacoes mais antigas sao descartadas).
        max_por_fonte: maximo de noticias retornadas por fonte.

    Returns:
        Lista de dicts com as chaves fonte, titulo, url, texto_base,
        data_publicacao e score, ordenada por score decrescente.
        Nunca levanta excecao: se uma fonte falhar, o aviso vai para o
        console e o resultado da outra fonte e retornado normalmente.
    """
    dias = max(int(dias), 1)
    max_por_fonte = max(int(max_por_fonte), 1)

    noticias: list[dict] = []

    for nome, coletor in (("HN", _coletar_hn), ("Reddit", _coletar_reddit)):
        try:
            resultado = coletor(dias, max_por_fonte)
        except Exception as erro:  # rede, parsing ou bug inesperado: nao derruba a coleta
            print(f"[aviso] falha inesperada na fonte {nome}: {erro!r}")
            continue

        if not resultado:
            print(f"[aviso] fonte {nome} nao retornou noticias (API fora do ar ou sem resultados).")
        noticias.extend(resultado)

    noticias.sort(key=lambda n: n["score"], reverse=True)
    return noticias


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    coletadas = coletar_noticias(dias=3, max_por_fonte=5)

    print(f"\n{len(coletadas)} noticias coletadas com sucesso.")
    if coletadas:
        print("3 primeiros titulos:")
        for noticia in coletadas[:3]:
            print(f"  [{noticia['fonte']}] {noticia['titulo']}")
    else:
        print("nenhuma noticia coletada (verifique a conexao de rede).")
