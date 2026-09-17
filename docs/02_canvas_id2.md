# Canvas de Planejamento — Automação "Boletim IA"

**Disciplina:** AI Factory — Etapa 1
**Entrega:** Critério 2 (ID 2)
**Autoria:** Emily Cristofoleti (individual)
**Data:** 17/09/2026

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Projeto | Automação "Boletim IA" |
| Problema endereçado | Curadoria manual, descentralizada e sem histórico das notícias de IA |
| Equipe | Individual |
| Papel | Emily Cristofoleti — escopo, decisões técnicas, validação e documentação |
| Prazo da entrega | 17/09/2026 (Etapa 1) |
| Custo de infraestrutura | Zero (sem chave de API, tudo local) |

## 2. Objetivos (SMART)

**Objetivo geral:** entregar um pipeline automatizado que colete notícias atuais de IA e as devolva em formato consumível (roteiro em pt-BR + áudio + registro histórico), sem dependência de serviços pagos.

| # | Objetivo | S | M | A | R | T | Situação |
|---|---|---|---|---|---|---|---|
| O1 | Entregar pipeline executável por um único comando (`python main.py`) que colete ao menos 10 notícias de IA, gere roteiro em pt-BR e produza WAV + registro em SQLite | Pipeline único, 4 etapas integradas | ≥10 notícias, WAV íntegro, 1 registro por execução | Depende apenas de ferramentas locais já instaladas | É o núcleo do critério de protótipo (ID 2.1/2.2) | Concluído em 17/09/2026 | **Atingido**: 20 notícias, roteiro de 3.185 chars, WAV de 201,33 s, registro id=1 (audio preservado como `audio/boletim_2026-09-17_primeira_execucao.wav`; uma segunda execucao completa no mesmo dia gerou o registro id=2, 121,07 s, comprovando a reprodutibilidade) |
| O2 | Manter custo de operação em zero, sem chave de API e sem serviço em nuvem | Fontes públicas, LLM e TTS locais | Nenhuma credencial exigida para executar | Já validado no ambiente disponível | Reduz custo recorrente e elimina dependência externa | Concluído em 17/09/2026 | **Atingido**: HN Algolia + Reddit RSS, Ollama local, Kokoro ONNX local |
| O3 | Documentar o projeto (README, diagnóstico e este Canvas) com decisões justificadas e limitações declaradas | Documentos ligados ao repositório | README com execução reproduzível e evidências | Escopo compatível com o prazo de 1 dia | Base para avaliação dos critérios 1, 2 e 3 | 17/09/2026 | Em fechamento |
| O4 | Preservar histórico versionado que comprove a evolução do trabalho, uma tarefa por commit | Repositório Git no GitHub | Histórico completo em `origin/main`, uma tarefa por commit | Fluxo simples de commit por tarefa | Atende ao critério de originalidade da entrega | 17/09/2026 | **Atingido**: 11 commits, de `a67819e` (S1) a `fe05247` (S10) |

## 3. Escopo

**Dentro do escopo:** coleta em fontes públicas sem chave, curadoria/resumo por LLM local, síntese de voz local, persistência em banco simples, orquestração em um comando e documentação.

**Fora do escopo (roadmap):** orquestração em n8n, scraping das URLs originais, upgrade para modelo 7B+, publicação como podcast/feed e interface web.

**Premissas:** máquina com Windows, Python 3.11 e Ollama em execução; download prévio dos modelos de voz (~354 MB).

## 4. Etapas e entregáveis

| Etapa | Entregável | Evidência |
|---|---|---|
| S0 | `CONTEXTO.md` com propósito, ambiente, regras, estado e fila | Arquivo versionado na raiz |
| S1 | Ambiente de áudio pronto: ffmpeg, `soundfile`, modelos Kokoro e smoke test de TTS pt-BR | `audio/smoke.wav` (3,69 s, RMS 0,055), `scripts/download_kokoro.py`, `scripts/smoke_kokoro.py` |
| S2 | Módulo de coleta (HN + Reddit) | `src/coletor.py`, commit `8928cb1` |
| S3 | Módulo de curadoria/resumo via Ollama | `src/boletim.py`, commit `45f3603` |
| S4 | Regra anti-alucinação no prompt + módulo de síntese de voz | `src/boletim.py`, `src/audio.py`, commit `05a427d` |
| S5 | Registro em SQLite + orquestrador de ponta a ponta + execução E2E | `src/registro.py`, `main.py`, `boletim.db`, commit `a9636ab` |
| S6 | Higiene do repositório (binários fora do versionamento) + README final | `.gitignore`, `README.md`, commit `e0d8154` |
| S7 | `requirements.txt` com versões fixadas + documentos de entrega (diagnóstico ID 1.1 e Canvas ID 2) | `requirements.txt`, `docs/01_diagnostico_id1_1.*`, `docs/02_canvas_id2.*`, commits `a22dc11` e `033daf7` |
| S8 | Remoção do caminho morto da coleta do Reddit (a rota JSON responde 403 em todas as execuções) | `src/coletor.py`, commit `0c76634` |
| S9 | Regularização das evidências E2E na documentação (duas execuções registradas, áudio da primeira preservado) | `README.md`, `docs/01`, `docs/02`, commit `a0db252` |
| S10 | Correção do tamanho do banco na documentação (2 registros / 16.384 B) | `README.md`, `CONTEXTO.md`, commit `fe05247` |

## 5. Papéis e responsabilidades

| Papel | Responsável | Atribuições |
|---|---|---|
| Autoria e decisão | Emily Cristofoleti | Definição do problema e do escopo, escolha de tecnologia, aprovação de cada etapa, execução e validação dos testes, redação da documentação |
| Implementação assistida | Assistentes de IA (agentes de código) | Escrita do código sob direção, uma tarefa por sessão, sempre validada pela autora com execução real antes de ser aceita |
| Verificação | Emily Cristofoleti | Conferência das saídas (WAV, roteiro, banco) e do histórico de commits |

O uso de assistentes de IA é declarado de forma transparente: as decisões, a validação e a documentação são humanas; o histórico de commits registra a evolução tarefa por tarefa.

## 6. Recursos necessários

- **Hardware:** máquina local com espaço em disco para os modelos (~354 MB) e para os áudios gerados.
- **Software:** Python 3.11 + pip, `requests`, `kokoro-onnx` 0.6.1, `numpy`, `onnxruntime`, `phonemizer`, `espeakng-loader`, `soundfile` 0.14.0, `edge-tts` 7.2.8, ffmpeg no PATH, Ollama com `qwen2.5:3b`, Git.
- **Fontes de dados:** API pública do Hacker News (Algolia) e feeds RSS Atom do Reddit — ambas anônimas.
- **Custo recorrente:** nenhum.

## 7. Riscos e mitigação (riscos reais vividos no projeto)

| # | Risco | Impacto | Mitigação aplicada | Resultado |
|---|---|---|---|---|
| R1 | Modelos do Kokoro indisponíveis no Hugging Face (HTTP 401 para acesso anônimo) | Bloqueio total da etapa de áudio | Fallback automático para as releases oficiais no GitHub dentro de `scripts/download_kokoro.py` | Resolvido (S1) |
| R2 | Arquivos acima de 100 MB são rejeitados pelo GitHub | Push impossível | `models/` no `.gitignore` + script de download reiniciável para reconstruir o ambiente | Resolvido (S1) |
| R3 | Reddit bloqueia o acesso anônimo ao endpoint JSON com HTTP 403, independente do User-Agent | Fonte de notícias indisponível | Uso da rota RSS Atom (`/<sub>/new/.rss`), que responde 200, como única rota do Reddit — o caminho JSON foi removido do código | Resolvido (S2, refinado na S8) |
| R4 | Limite de requisições anônimas do Reddit (~1/min por IP) retorna HTTP 429 | Coleta abortada no meio | Espera de 60 s antes de nova tentativa e redução do número de fontes por rodada | Resolvido (S2) |
| R5 | Alucinação do modelo 3B: detalhes inventados em títulos sem texto de apoio | Roteiro com informação imprecisa | Regra anti-alucinação no prompt de sistema (proíbe inventar fatos, empresas e siglas; sem texto de apoio, usa apenas o título) + limitação documentada no README | Mitigado parcialmente (risco residual aceito) |
| R6 | Artefatos gerados (banco e áudios) entrarem no versionamento | Repositório inflado e push inviável | `.gitignore` com `*.db`, `audio/boletim_*.wav` e `output/` + `git rm --cached` sem apagar arquivos do disco + validação com `git ls-files` | Resolvido (S6) |
| R7 | Prazo de 1 dia para escopo amplo | Entrega incompleta | Corte de escopo: n8n fora da entrega e nenhuma dependência que exija chave de API; execução em sessões curtas encadeadas (S1–S10), cada uma com commit | Resolvido |
| R8 | Dependência de serviço externo de TTS e de rede instável | Falha na geração de áudio | TTS 100% local (Kokoro ONNX), operando offline após o download dos modelos | Resolvido (S1/S4) |
| R9 | Repetição da mesma noticia na narracao (LLM reciclando itens para preencher blocos tematicos) | Roteiro e audio redundantes, qualidade da entrega prejudicada | Diagnostico pelo roteiro gravado no banco + troca para formato linear, regra de mencao unica, proibicao de citar fonte/URL/data e repeat_penalty (1.2, repeat_last_n 1024) no Ollama | Resolvido (S13) |

## 8. Critérios de aceite e evidências

| Requisito da rubrica | Artefato que comprova |
|---|---|
| ID 1.1 — diagnóstico da necessidade (Critério 1) | `docs/01_diagnostico_id1_1.md` |
| ID 2 — planejamento / Canvas (Critério 2) | `docs/02_canvas_id2.md` (este documento) |
| ID 2.1 — chamada a API pública | `src/coletor.py` + saída da coleta registrada no README |
| ID 2.1 — resposta do LLM | `src/boletim.py` + trecho do roteiro registrado no README |
| ID 2.2 — síntese de voz (TTS) | `src/audio.py` + `audio/boletim_2026-09-17_primeira_execucao.wav` (201,33 s) |
| ID 2.2 — gravação em banco simples | `src/registro.py` + `boletim.db` (tabela `boletins`, registros `id=1` e `id=2`) |
| Integração fluida de ponta a ponta | `main.py` executado com sucesso (evidência de terminal no README) |
| Originalidade (critério de anulação) | Histórico de commits em `origin/main` (S1–S10) e repositório público |

## 9. Cronograma executado (17/09/2026)

| Ordem | Sessão | Foco | Commit |
|---|---|---|---|
| 1 | S0 | Contexto e regras do projeto | (arquivo versionado em S1) |
| 2 | S1 | Ambiente de áudio e modelos de voz | `a67819e` |
| 3 | S2 | Coleta de notícias | `8928cb1` |
| 4 | S3 | Curadoria/resumo via LLM | `45f3603` |
| 5 | S4 | Anti-alucinação + síntese de voz | `05a427d` |
| 6 | S5 | Banco SQLite + orquestrador + teste E2E | `a9636ab` |
| 7 | S6 | Higiene do repositório + README | `e0d8154` |
| 8 | S7 | `requirements.txt` + documentos de entrega | `a22dc11`, `033daf7` |
| 9 | S8 | Remoção do código morto (rota JSON do Reddit) | `0c76634` |
| 10 | S9 | Regularização das evidências E2E na documentação | `a0db252` |
| 11 | S10 | Correção do tamanho do banco na documentação | `fe05247` |
