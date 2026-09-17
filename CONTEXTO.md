# CONTEXTO DO PROJETO (executor: DeepSeek local)

## 1. Propósito
- Automação "Boletim IA": gera um boletim com notícias atuais do mercado de Inteligência Artificial.
- Pipeline: (input) API pública de notícias sem chave -> (process) curadoria/resumo via LLM local Ollama (qwen2.5:3b) -> (output) áudio do boletim via Kokoro TTS (kokoro-onnx) + gravação em SQLite.
- Entrega da disciplina AI Factory, Etapa 1 (IDs 1.1, 2, 2.1, 2.2).

## 2. Ambiente (verdade atual)
- Windows / PowerShell / editor Zed. Raiz: C:\Users\emily\OneDrive\Documentos\git\faculdade-automacao-relatorio
- Python 3.11.9 + pip funcional. Pacotes: requests 2.34.2, kokoro-onnx 0.6.1, edge-tts 7.2.8, numpy 2.4.6, onnxruntime, phonemizer, espeakng-loader, soundfile 0.14.0.
- Sem chaves de API (decisao de seguranca): nao usamos servicos que exigem credencial (NewsAPI, GNews, Reddit OAuth). Coleta apenas em fontes publicas e anonimas.
- Reddit anonimo a partir desta rede: r/<sub>/new.json responde 403 (bloqueio do Reddit para este IP, com qualquer User-Agent); o fallback r/<sub>/new/.rss (Atom) responde 200. Rate limit anonimo baixo: ~1 requisicao/min por IP (x-ratelimit-reset ~40-60 s) -> HTTP 429 se exceder.
- HN Algolia (hn.algolia.com/api/v1/search_by_date) responde 200 sem chave.
- Ollama ativo em http://localhost:11434, modelo qwen2.5:3b baixado.
- ffmpeg 9.0.1 (gyan.dev full build) disponivel no PATH. NAO usado ate agora.
- Kokoro modelos em models/ (kokoro-v1.0.onnx 325.505.369 B, voices-v1.0.bin 28.214.398 B), baixados na sessao 1 via scripts/download_kokoro.py.
- Fonte dos modelos: a URL do HuggingFace (https://huggingface.co/thewh1teagle/kokoro-onnx/resolve/main/model_files/) responde 401 para acesso anonimo (repo privado/removido); o script cai no fallback das releases oficiais do GitHub (https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1).
- models/ esta no .gitignore (arquivos > 100 MB, limite do GitHub). Reconstruir com: python scripts/download_kokoro.py
- Nao confirmados: pyttsx3.
- Sobras de sessao anterior citadas no CONTEXTO (bench_ollama.py, scripts/smoke_sqlite.py): NAO existem no working copy na sessao 1. `scripts/smoke_kokoro.py` foi criado nesta sessao (nao e sobra).

## 3. Regras fixas do executor
- Iniciar toda sessao lendo este arquivo inteiro, antes de qualquer acao.
- Executar SOMENTE a tarefa do prompt atual; nao criar funcionalidades fora do escopo.
- Validar toda tarefa rodando o codigo (se tiver acesso a terminal); senao, fornecer os comandos PowerShell exatos e aguardar o output colado pelo humano antes de fechar a tarefa.
- Ao concluir: atualizar as secoes 4, 5 e 6 deste arquivo ANTES de responder; criar commit git com mensagem "task N: descricao curta".
- Usar apenas pacotes da secao 2; instalar pacote novo somente se indispensavel, registrando no log.
- Scripts executaveis a partir da raiz do projeto, caminhos relativos, mensagens de erro claras.
- Resposta final sempre em pt-BR e curta: o que fez / arquivos criados ou alterados / como testar / avisos.

## 4. Estado atual
- Sessao 1 concluida: ambiente de audio pronto (TTS testado, audio/smoke.wav OK).
- Sessao 2 concluida: Input do pipeline pronto em src/coletor.py (`coletar_noticias(dias, max_por_fonte)` -> HN + Reddit normalizados).
- Pipeline: Input OK (src/coletor.py) + Output/TTS validado (kokoro). FALTAM o Process (curadoria/resumo via LLM Ollama qwen2.5:3b) e o DB (SQLite).
- Reddit nesta rede: apenas a rota Atom (.rss) funciona -> nessa rota score = 0 (o endpoint JSON traria upvotes, mas esta bloqueado).
- HN: poucas historias trazem `story_text`, entao `texto_base` costuma vir vazio nos itens do HN.
- ffmpeg 9.0.1-full_build-www.gyan.dev (confirmado no PATH nesta sessao).
- soundfile 0.14.0 instalado (traz cffi 2.1.1, pycparser 3.0).
- Modelos Kokoro em models/: kokoro-v1.0.onnx (325.505.369 B) e voices-v1.0.bin (28.214.398 B).
- Smoke test pt-BR OK: audio/smoke.wav (177.260 B, 24000 Hz, 3.69 s, voz pf_dora, RMS 0.055).
- Vozes pt-BR disponiveis no voices-v1.0.bin: pf_dora, pm_alex, pm_santa (convencao Kokoro: 1o char = idioma, 2o = genero).
- Voz pt-BR exige espeak-ng para fonemizacao: funciona via espeakng-loader, sem instalacao extra.

## 5. Log de tarefas
| # | Data | Tarefa | Status | Notas |
|---|------|--------|--------|-------|
| 0 | 2026-09-17 | Criacao do CONTEXTO.md | OK | sessao 0 |
| 1 | 2026-09-17 | Preparacao ambiente audio (ffmpeg, soundfile, kokoro download, smoke) | OK | ffmpeg 9.0.1 ja no PATH; soundfile 0.14.0 instalado; HF deu 401 -> fallback GitHub releases; smoke.wav 177 KB; models/ fora do git (>100 MB) |
| 2 | 2026-09-17 | Modulo coletor HN+Reddit (src/coletor.py) | OK | smoke `python src/coletor.py` (dias=3, max_por_fonte=5) -> 10 noticias (5 HN + 5 Reddit); Reddit .json deu 403 -> fallback .rss com espera de 60 s no 429; requests 2.34.2 |

## 6. Fila (definida exclusivamente pelo orquestrador)
- (vazia; a proxima tarefa chega por prompt)
