# CONTEXTO DO PROJETO (executor: DeepSeek local)

## 1. Propósito
- Automação "Boletim IA": gera um boletim com notícias atuais do mercado de Inteligência Artificial.
- Pipeline: (input) API pública de notícias sem chave -> (process) curadoria/resumo via LLM local Ollama (qwen2.5:3b) -> (output) áudio do boletim via Kokoro TTS (kokoro-onnx) + gravação em SQLite.
- Entrega da disciplina AI Factory, Etapa 1 (IDs 1.1, 2, 2.1, 2.2).

## 2. Ambiente (verdade atual)
- Windows / PowerShell / editor Zed. Raiz: C:\Users\emily\OneDrive\Documentos\git\faculdade-automacao-relatorio
- Python 3.11.9 + pip funcional. Pacotes: requests 2.34.2, kokoro-onnx 0.6.1, edge-tts 7.2.8, numpy 2.4.6, onnxruntime, phonemizer, espeakng-loader, soundfile 0.14.0.
- Sem chaves de API (decisao de seguranca): nao usamos servicos que exigem credencial (NewsAPI, GNews, Reddit OAuth). Coleta apenas em fontes publicas e anonimas.
- Reddit anonimo a partir desta rede: a rota r/<sub>/new.json responde 403 (bloqueio do Reddit para este IP, com qualquer User-Agent); ela foi REMOVIDA do codigo (task 8) e a unica rota usada e o feed Atom r/<sub>/new/.rss, que responde 200. Rate limit anonimo baixo: ~1 requisicao/min por IP (x-ratelimit-reset ~40-60 s) -> HTTP 429 se exceder, com espera de REDDIT_ESPERA_429 s (60 s) e uma nova tentativa.
- HN Algolia (hn.algolia.com/api/v1/search_by_date) responde 200 sem chave.
- Ollama ativo em http://localhost:11434, modelo qwen2.5:3b baixado.
- ffmpeg 9.0.1 (gyan.dev full build) disponivel no PATH. NAO usado ate agora.
- Kokoro modelos em models/ (kokoro-v1.0.onnx 325.505.369 B, voices-v1.0.bin 28.214.398 B), baixados na sessao 1 via scripts/download_kokoro.py.
- Fonte dos modelos: a URL do HuggingFace (https://huggingface.co/thewh1teagle/kokoro-onnx/resolve/main/model_files/) responde 401 para acesso anonimo (repo privado/removido); o script cai no fallback das releases oficiais do GitHub (https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1).
- models/ esta no .gitignore (arquivos > 100 MB, limite do GitHub). Reconstruir com: python scripts/download_kokoro.py
- Vozes pt-BR disponiveis no voices-v1.0.bin: pf_dora, pm_alex, pm_santa (convencao Kokoro: 1o char = idioma, 2o = genero). A voz pt-BR exige espeak-ng para fonemizacao, suprido pelo espeakng-loader (sem instalacao extra).

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
- Sessao 3 concluida: Process pronto em src/boletim.py (`gerar_boletim(noticias)` -> roteiro pt-BR via Ollama /api/chat, modelo qwen2.5:3b, stream=False, temperature=0.6).
- Sessao 4 concluida: Output/Audio pronto em src/audio.py (`sintetizar_audio(texto, caminho_saida)` -> WAV 16-bit PCM, 24000 Hz, voz pf_dora; limpa markdown, quebra o roteiro em chunks de ate 400 chars e insere 0,12 s de silencio entre eles; modelo Kokoro carregado 1x por processo via lru_cache).
- Anti-alucinacao: regra critica acrescentada ao PROMPT_SISTEMA de src/boletim.py (proibe inventar fatos/empresas/detalhes/siglas; com texto_base curto ou vazio, so apresentar o titulo sem especular).
- Teste anti-alucinacao (3 noticias do HN, todas SEM texto_base, `python src/audio.py`): sumiram as invencoes observadas na sessao 3 ("Language Models Large", "Proprietary Control Layer", "The Machine Learning Research"); a sigla PLC saiu com a expansao correta (Programmable Logic Controllers).
- Risco residual: em titulos curtos do HN o LLM ainda extrapola detalhes pontuais (ex.: "Union Alpha Stealth Model" -> descrito como modelo aberto da Cloudflare, o que nao esta no titulo). Todo o risco se concentra nos itens do HN, que vem sem texto_base.
- Pipeline COMPLETO funcionando de ponta a ponta (Coleta -> LLM -> TTS -> DB): `python main.py` orquestra as 4 etapas em sequencia. Pronto para a documentacao final.
- Sessao 5 concluida: registro em SQLite (src/registro.py) + orquestrador (main.py).
- src/registro.py: `inicializar_banco(caminho_db="boletim.db")` cria a tabela `boletins` (id INTEGER PRIMARY KEY, data_geracao TEXT, qtd_noticias INTEGER, texto_boletim TEXT, caminho_audio TEXT, duracao_audio_segundos REAL); `registrar_boletim(...)` insere e retorna o lastrowid. Apenas sqlite3 da stdlib.
- main.py (raiz): inicializar_banco -> coletar_noticias(dias=1, max_por_fonte=10) -> gerar_boletim -> sintetizar_audio em audio/boletim_<YYYY-MM-DD>.wav -> duracao via sf.read (len(amostras)/taxa) -> registrar_boletim -> print do resumo. Cada etapa tem try/except com mensagem clara e retorna codigo 1 em caso de falha; sem noticias, imprime aviso e encerra sem gerar boletim.
- E2E (2026-09-17): 1a execucao (02:34:21) = registro id=1, 20 noticias (HN + Reddit), roteiro de 3185 chars, audio de 201,33 s (4.831.903 amostras, 24000 Hz, PCM_16, 11 chunks, 9.663.850 B); o audio dessa execucao esta preservado em audio/boletim_2026-09-17_primeira_execucao.wav porque o nome do WAV usa a data do dia. 2a execucao (04:15:57) = registro id=2, 20 noticias, 121,07 s, gravada em audio/boletim_2026-09-17.wav. boletim.db (16.384 B, 2 registros) concentra as duas execucoes.
- Geracao de texto testada: `python src/boletim.py` (dias=2, max_por_fonte=3) -> 6 noticias -> output/boletim_texto.md (2520 chars, pt-BR coeso, ~1 min de geracao).
- O LLM recebe APENAS fonte/titulo/url/texto_base do coletor: sem scraping das URLs originais. Em titulos curtos do HN (sem texto_base) o modelo tende a inferir contexto -> risco de imprecisao no roteiro.
- Reddit nesta rede: o caminho JSON morto (403 com qualquer User-Agent) foi removido do codigo na task 8; a unica rota e o feed Atom (.rss) e o score dos itens do Reddit e sempre 0 (o feed nao expoe upvotes).
- HN: poucas historias trazem `story_text`, entao `texto_base` costuma vir vazio nos itens do HN.
- Smoke test pt-BR OK (sessao 1): audio/smoke.wav (177.260 B, 24000 Hz, 3.69 s, voz pf_dora, RMS 0.055).
- Higiene do git (tarefa 6): boletim.db, audio/boletim_*.wav e output/ estao FORA do git (destrackeados com `git rm --cached`, arquivos intactos no disco) e cobertos pelo .gitignore; sao artefatos de execucao, reconstruiveis rodando `python main.py`. audio/smoke.wav segue versionado de proposito.
- README.md da entrega CRIADO na raiz (tarefa 6): visao geral, problema/solucao, diagrama do pipeline, estrutura, stack, setup/execucao, decisoes tecnicas, evidencias, limitacoes e roadmap.
- requirements.txt na raiz com versoes fixadas (inclui Markdown, opcional para gerar os PDFs); .gitignore cobre tambem docs/*.html (HTML intermediario do gerador).
- Documentos de entrega em docs/: `01_diagnostico_id1_1.md`/.pdf (Criterio 1 / ID 1.1) e `02_canvas_id2.md`/.pdf (Criterio 2 / ID 2). Gerados com `scripts/md_para_pdf.py` (Markdown -> HTML) + Chrome headless (`--print-to-pdf`).
- Revisao final do codigo (pente fino): os 4 modulos + main.py + scripts compilam (`python -m compileall`); boletim.db tem 2 registros (id=1 e id=2, um por execucao); os WAV conferem (audio/boletim_2026-09-17_primeira_execucao.wav 4.831.903 amostras / 24000 Hz / PCM_16 / 201,33 s; audio/boletim_2026-09-17.wav 121,07 s; boletim_completo.wav 72,80 s; smoke.wav 3,69 s); models/ com 325.505.369 B + 28.214.398 B. Nenhum caminho absoluto ou caminho inexistente no codigo. Decisao: main.py usa caminhos relativos a raiz por design (documentado), entao NAO foi alterado, para nao invalidar a evidencia E2E ja registrada.
- Canvas ID2 alinhado ao historico real (tarefa 11): docs/02_canvas_id2.md/.pdf com tabela de etapas (S7-S10), cronograma (11 commits, a67819e a fe05247), objetivo O4 corrigido e checklist de evidencias apontando o audio preservado e os registros id=1 e id=2.

## 5. Log de tarefas
| # | Data | Tarefa | Status | Notas |
|---|------|--------|--------|-------|
| 0 | 2026-09-17 | Criacao do CONTEXTO.md | OK | sessao 0 |
| 1 | 2026-09-17 | Preparacao ambiente audio (ffmpeg, soundfile, kokoro download, smoke) | OK | ffmpeg 9.0.1 ja no PATH; soundfile 0.14.0 instalado; HF deu 401 -> fallback GitHub releases; smoke.wav 177 KB; models/ fora do git (>100 MB) |
| 2 | 2026-09-17 | Modulo coletor HN+Reddit (src/coletor.py) | OK | smoke `python src/coletor.py` (dias=3, max_por_fonte=5) -> 10 noticias (5 HN + 5 Reddit); Reddit .json deu 403 -> fallback .rss com espera de 60 s no 429; requests 2.34.2 |
| 3 | 2026-09-17 | Gerador de boletim via Ollama | OK | Teste passou. |
| 4 | 2026-09-17 | Ajuste LLM + Modulo Audio Kokoro | OK | Audio gerado com sucesso: audio/boletim_completo.wav 3.494.506 B (3412,6 KB), 1747231 amostras, 24000 Hz, PCM_16, 72,80 s, 4 chunks, voz pf_dora; src/audio.py criado; prompt anti-alucinacao em src/boletim.py. |
| 5 | 2026-09-17 | Orquestrador main.py + DB SQLite | OK | Teste E2E passou. |
| 6 | 2026-09-17 | Higiene do git (.gitignore + destrackeamento) + README final | OK | .gitignore com *.db, audio/boletim_*.wav e output/; `git rm --cached` em boletim.db, audio/boletim_2026-09-17.wav, audio/boletim_completo.wav e output/boletim_texto.md (arquivos mantidos no disco); README.md criado com 10 secoes e evidencia real do SQLite; commit de task 6 enviado ao origin/main. |
| 7 | 2026-09-17 | Revisao final + requirements.txt + documentos de entrega (ID 1.1 e ID 2) | OK | requirements.txt com versoes fixadas; .gitignore cobre docs/*.html; README estrutura/instalacao atualizadas; CONTEXTO com secao 4 limpa; docs/ com 2 MD + 2 PDF; commit da task 7 publicado |
| 8 | 2026-09-17 | Remocao do caminho JSON morto do coletor do Reddit | OK | saidas: _posts_via_json, REDDIT_JSON_TEMPLATE e REDDIT_LIMIT removidos; _posts_reddit usa direto o feed Atom; README e CONTEXTO alinhados; Canvas ID2 (R3) atualizado; smoke `python src/coletor.py` sem avisos de JSON |
| 9 | 2026-09-17 | Regularizacao das evidencias E2E na documentacao | OK | README secao 8/9, docs/01 e docs/02 atualizados (2 execucoes: id=1 201,33 s preservado como _primeira_execucao.wav; id=2 121,07 s); PDFs regenerados; codigo nao alterado |
| 10 | 2026-09-17 | Correcao do tamanho do boletim.db na documentacao (2 registros / 16.384 B) | OK | README secao 8 e CONTEXTO secao 4 alinhados ao tamanho real do banco apos a 2a execucao |
| 11 | 2026-09-17 | Alinha Canvas ID2 ao historico real de commits | OK | docs/02_canvas_id2.md/.pdf: etapas S7-S10, cronograma com 11 commits, O4 com contagem correta, checklist de evidencias atualizado; PDF regenerado com Chrome headless e HTML intermediario apagado |

## 6. Fila (definida exclusivamente pelo orquestrador)
- (vazia; a proxima tarefa chega por prompt)
