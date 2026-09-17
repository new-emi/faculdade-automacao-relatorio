"""Modulo de processamento do pipeline "Boletim IA" (Process).

Recebe a lista de noticias normalizada pelo coletor (Input) e usa o LLM local
servido pelo Ollama para escrever o roteiro do boletim em pt-BR.

O LLM trabalha APENAS com o que o coletor entregou (fonte, titulo, url e
texto_base). Este modulo NAO faz scraping das URLs originais.

O roteiro e LINEAR por design: introducao curta, noticias apresentadas uma a uma
na ordem da lista e conclusao breve. O prompt proibe blocos/secoes tematicas (que
levavam o modelo a reciclar noticias para preencher os blocos), a repeticao de um
item, a mencao a fonte/URL e a citacao de datas.

A geracao acontece em LOTES de TAMANHO_LOTE noticias: com a lista inteira de uma vez,
um modelo de 3B omitia itens. Cada lote produz um trecho do roteiro (a abertura fica no
primeiro e a conclusao no ultimo) e os trechos sao concatenados na ordem da lista.

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

# Noticias por chamada ao LLM. Com a lista inteira (10 itens ou mais) o modelo de 3B
# resumia/omitia noticias; em lotes pequenos ele cobre o que recebe.
TAMANHO_LOTE = 5

PROMPT_SISTEMA = (
    "Voce e o ancora do 'Boletim IA', um podcast/relatorio diario sobre o mercado de "
    "Inteligencia Artificial. Seu tom e profissional, dinamico, claro e em PT-BR. Voce deve "
    "criar um roteiro fluido para ser lido em voz alta. "
    "ESTRUTURA LINEAR: as noticias sao apresentadas uma a uma, na ordem recebida, em texto "
    "corrido, sem blocos nem secoes tematicas (por exemplo, 'Tendencias de X', 'Novidades em "
    "Y'), porque agrupar por tema obriga a repetir noticias. O roteiro e escrito em trechos: "
    "as instrucoes de abertura, de continuacao e de fechamento vem na mensagem do usuario — "
    "siga exatamente o papel pedido para o trecho atual. "
    "COBERTURA TOTAL: a lista do trecho recebido e curta de proposito, entao cubra TODAS as "
    "noticias dela, uma por vez, sem omitir nenhuma. Quando nao houver informacao alem do "
    "titulo, apresente o titulo de forma natural, sem juntar duas noticias numa mesma frase. "
    "Mencao unica: cada noticia aparece EXATAMENTE UMA VEZ no roteiro. Nunca cite a mesma "
    "noticia, produto, empresa ou fato duas vezes. Se duas entradas tratarem do mesmo "
    "assunto, cite apenas uma e siga adiante. "
    "NUNCA escreva a fonte nem prefixos tecnicos no texto: nada de 'HN:', 'Reddit:', "
    "'Show HN:', 'Ask HN:', nem URLs. Cite apenas o titulo, de forma natural. "
    "NAO cite data, dia, mes, ano ou horario; para se referir ao momento, use no maximo 'hoje'. "
    "CONCISAO: 1 ou 2 frases por noticia, trecho de no maximo cerca de 1.200 caracteres, em "
    "texto corrido, sem marcadores de lista, sem asteriscos e sem titulos em negrito. "
    "Nunca afirme que a cobertura esta completa, nem avalie ou elogie a qualidade do proprio "
    "texto. "
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


def _dividir_em_lotes(noticias: list[dict], tamanho: int = TAMANHO_LOTE) -> list[list[dict]]:
    """Divide as noticias em lotes de no maximo `tamanho` itens, na ordem original."""
    if tamanho < 1:
        raise ValueError("tamanho do lote precisa ser >= 1 noticia.")
    return [noticias[i : i + tamanho] for i in range(0, len(noticias), tamanho)]


def _montar_prompt_lote(
    noticias: list[dict],
    indice: int,
    total: int,
) -> str:
    """Monta a mensagem de usuario de um lote, definindo o papel do trecho.

    O texto ja gerado NAO e repassado ao lote seguinte: o modelo de 3B tendia a repetir
    o trecho copiado na resposta (ex.: comecar o trecho novo com as ultimas palavras do
    anterior). Basta a instrucao de continuidade.

    Args:
        noticias: noticias do lote.
        indice: posicao do lote (1-based).
        total: quantidade total de lotes.
    """
    partes = [
        f"Noticias deste trecho ({len(noticias)} itens; trecho {indice} de {total}), no "
        "formato 'Fonte | Titulo | URL | Texto Base':",
        "",
        _formatar_noticias(noticias),
        "",
        "Escreva APENAS o trecho do roteiro do Boletim IA correspondente a estas noticias, "
        "cobrindo TODAS elas, uma por vez, com 1 ou 2 frases cada, em texto corrido.",
    ]

    if indice == 1:
        partes.append("Comece com uma introducao curta (2 ou 3 frases).")
    else:
        partes.append(
            f"Este e o trecho {indice} de {total}: CONTINUE o roteiro a partir do trecho "
            "anterior, sem nova introducao, sem repetir o que ja foi dito, sem se despedir e "
            "sem copiar palavras do texto anterior."
        )

    if indice == total:
        partes.append("Termine com uma conclusao breve (2 ou 3 frases) e encerre o roteiro.")
    else:
        partes.append("NAO escreva conclusao nem despedida neste trecho.")

    partes.append(
        "Nao repita noticias de trechos anteriores, nao cite fonte, URL ou data, nao invente "
        "fatos, numeros ou citacoes e nunca afirme que a cobertura esta completa nem avalie a "
        "qualidade do proprio texto."
    )
    return "\n".join(partes)


def _chamar_ollama(mensagem_usuario: str) -> str:
    """Envia uma mensagem ao Ollama e devolve o texto gerado.

    Raises:
        RuntimeError: se o Ollama estiver inacessivel ou responder em formato inesperado.
    """
    payload = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": mensagem_usuario},
        ],
        "stream": False,
        "options": {
            "temperature": TEMPERATURA,
            # repeat_penalty/repeat_last_n: penalizam a repeticao de trechos ao longo de
            # todo o trecho gerado; o default do repeat_last_n observa apenas 64 tokens.
            "repeat_penalty": 1.2,
            "repeat_last_n": 1024,
        },
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


def gerar_boletim(noticias: list[dict]) -> str:
    """Gera o roteiro do boletim em pt-BR a partir das noticias coletadas.

    As noticias sao enviadas ao LLM em lotes de TAMANHO_LOTE e os trechos gerados sao
    concatenados na ordem (a abertura fica no primeiro lote e a conclusao no ultimo).
    Enviar a lista inteira de uma vez fazia o modelo de 3B resumir/omitir noticias.

    Args:
        noticias: lista de dicts normalizados pelo coletor (fonte, titulo, url,
            texto_base, data_publicacao, score).

    Returns:
        Texto do roteiro em pt-BR, em texto corrido (sem markdown), pronto para ser
        lido em voz alta.

    Raises:
        ValueError: se a lista de noticias estiver vazia.
        RuntimeError: se o Ollama estiver inacessivel ou responder em formato inesperado.
    """
    noticias = list(noticias or [])
    if not noticias:
        raise ValueError("nenhuma noticia recebida: nada para o LLM processar.")

    lotes = _dividir_em_lotes(noticias)
    trechos: list[str] = []

    for indice, lote in enumerate(lotes, start=1):
        print(f"  lote {indice}/{len(lotes)} ({len(lote)} noticia(s))...")
        trechos.append(_chamar_ollama(_montar_prompt_lote(lote, indice, len(lotes))))

    return "\n\n".join(trechos)


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
