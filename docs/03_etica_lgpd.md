# Impacto Ético, LGPD e IA Responsável — Automação "Boletim IA"

**Disciplina:** AI Factory — Etapa final
**Entrega:** Critério 2 (ID 3.2)
**Autoria:** Emily Cristofoleti
**Data da análise:** 12/11/2026

---

## 1. O que o sistema trata, e onde cada dado fica

A análise começa pelo inventário: não dá para avaliar riscos de dados sem saber quais dados existem, de onde vêm, onde ficam e por quanto tempo.

| Dado | Origem | Onde fica | Tem dado pessoal? | Retenção |
|---|---|---|---|---|
| Notícias coletadas (título, URL, texto de apoio, data, score) | API pública do Hacker News e feed RSS do Reddit | Só na memória, durante a execução | Pode ter: nomes de pessoas citadas nas notícias e, no Reddit, o nome de usuário do autor dentro do texto do feed | Nenhuma: descartadas ao fim da execução |
| Roteiro gerado pelo LLM | Ollama (qwen2.5:3b), local | `boletim.db`, tabela `boletins` | Pode ter: nomes de figuras públicas citadas nas notícias | **12 meses**; depois o texto é apagado e só os metadados ficam |
| Áudio do boletim (WAV) | Kokoro TTS, local | Pasta `audio/` | Mesmo conteúdo do roteiro | **30 dias** |
| Métricas (latência, status, tempo por etapa) | `servidor.py` e `main.py` | `boletim.db`, tabelas `requisicoes` e `execucoes` | Não | Sem prazo (não há dado pessoal) |
| Token do bot e Chat ID do Telegram | Criados pela autora | Cofre de credenciais do n8n | Chat ID identifica a autora; o token é uma credencial | Enquanto o bot existir |
| Áudio e roteiro enviados ao Telegram | n8n | Servidores do Telegram (fora da máquina) | Mesmo conteúdo do roteiro | Regras do Telegram |

Duas decisões de projeto já reduzem o risco na origem:

- **Minimização na coleta.** O coletor não guarda o autor das publicações: os campos normalizados são só `fonte`, `titulo`, `url`, `texto_base`, `data_publicacao` e `score`. O único caminho por onde um nome de usuário passa é o texto do feed do Reddit, que vai ao LLM na memória e não é gravado.
- **Processamento local.** Coleta, LLM e síntese de voz rodam na máquina da autora. O único ponto em que o conteúdo sai da máquina é a entrega pelo Telegram.

## 2. Enquadramento na LGPD (Lei nº 13.709/2018)

### 2.1 O uso atual está fora do alcance da lei

O art. 4º, inciso I, diz que a LGPD não se aplica ao tratamento de dados pessoais *"realizado por pessoa natural para fins exclusivamente particulares e não econômicos"*. O Boletim IA, como está hoje, é usado só pela autora, para se manter atualizada, sem fins comerciais. Portanto, a rigor, a lei não se aplica.

### 2.2 Por que aplicar os princípios mesmo assim

Três motivos levam o projeto a seguir a LGPD como se ela se aplicasse:

1. **O código é público.** Qualquer pessoa pode reutilizá-lo num contexto em que a exceção do art. 4º não vale: uma empresa que gera boletins para a equipe, um podcast aberto, um produto pago. O projeto deve sair de fábrica pronto para esse cenário.
2. **A exceção depende do uso, não do código.** No dia em que o boletim for compartilhado com colegas ou usado no trabalho, o mesmo sistema passa a estar sob a lei, sem que uma linha de código mude.
3. **Boa prática profissional.** Privacidade desde a concepção (*privacy by design*) é mais barata do que adaptar depois.

### 2.3 Se a lei se aplicasse: base legal

Num cenário de uso compartilhado ou comercial, o tratamento dos nomes de pessoas citadas nas notícias se apoiaria em duas bases:

- **Dados tornados manifestamente públicos pelo titular** (art. 7º, §4º): notícias publicadas e posts em fóruns abertos. A própria lei ressalva que os direitos do titular e os princípios continuam valendo, então "é público" não autoriza qualquer uso.
- **Legítimo interesse** (art. 7º, IX): informar sobre o mercado de IA, com tratamento mínimo e sem perfilar ninguém.

### 2.4 Os princípios do art. 6º aplicados ao projeto

| Princípio | Como o projeto atende | Evidência |
|---|---|---|
| **Finalidade** (I) | Um propósito único e declarado: resumir notícias de IA. Os dados não são usados para nada além disso | README, seção 2 |
| **Necessidade** (III) | Coleta sem autor; política de retenção que apaga áudios com mais de 30 dias e roteiros com mais de 12 meses | `src/retencao.py`, chamado a cada execução bem-sucedida |
| **Transparência** (VI) | A documentação descreve cada etapa do tratamento e declara que roteiro e voz são gerados por IA; para uso público, o aviso iria no próprio áudio (risco E6) | README e este documento |
| **Segurança** (VII) e art. 46 | Processamento local, token fora do código, banco e áudios fora do repositório público | `.gitignore`; cofre de credenciais do n8n |
| **Responsabilização e prestação de contas** (X) | Cada pedido e cada execução ficam registrados com status, etapa e motivo de falha | Tabelas `requisicoes` e `execucoes` |

A **eliminação após o fim do tratamento** (art. 16) está implementada, e não só prometida: `src/retencao.py` tem modo de simulação (`python src/retencao.py` lista sem apagar) e só mexe em arquivos com o nome no padrão `boletim_AAAA-MM-DD.wav`, protegendo as evidências guardadas em `audio/evidencias/`.

## 3. Riscos e mitigação

| # | Risco | Impacto | Mitigação aplicada | Mitigação proposta |
|---|---|---|---|---|
| E1 | **Alucinação**: o modelo de 3B inventa detalhes que não estão na notícia | Alto: informação falsa entregue com voz confiante | Regra anti-alucinação no prompt (sem texto de apoio, só o título); geração em lotes de 5; revisão automática de idioma e de despedidas fora de lugar | Enviar no Telegram os links das notícias originais junto com o áudio, para o ouvinte conferir; testar um modelo maior |
| E2 | **Viés de fontes**: só Hacker News e Reddit, comunidades em inglês, majoritariamente técnicas e norte-americanas | Médio: visão estreita do mercado, sem o contexto brasileiro | Documentado como limitação | Incluir fontes plurais, como veículos brasileiros e blogs oficiais de laboratórios, e equilibrar a seleção entre elas |
| E3 | **Dados pessoais de terceiros** nas notícias (nomes, usuários) | Baixo no uso pessoal; médio se publicado | Coleta sem autor; nada do texto bruto é gravado; retenção | Remover o trecho "submitted by /u/…" do texto do Reddit antes de enviar ao LLM |
| E4 | **Termos de uso das fontes**: coleta automatizada pode violar regras da plataforma | Médio: bloqueio ou questionamento | Só endpoints públicos oficiais (API do HN e feed RSS); respeito ao limite de requisições (espera de 60 s quando o Reddit responde 429); nenhuma raspagem de HTML | Ver item 3.1: substituir o Reddit por fontes que oferecem acesso oficial |
| E5 | **Direitos autorais**: o roteiro resume conteúdo de terceiros | Baixo no uso pessoal; alto se o boletim virar podcast público | O roteiro parafraseia títulos e trechos curtos, sem reproduzir os textos | Para publicação: citar as fontes no áudio e na descrição, e avaliar as regras de cada veículo |
| E6 | **Voz sintética** confundida com voz humana | Médio se publicado | O áudio é de uso pessoal | Abrir cada boletim publicado com "boletim gerado por inteligência artificial" |
| E7 | **Credencial exposta**: o token do bot chegou a ficar escrito num comentário do `servidor.py` | Alto: quem tem o token controla o bot | Comentário removido; busca no histórico do git (`git log -S`) confirmou que o token nunca foi para um commit; token guardado só no cofre do n8n | Gerar um token novo no @BotFather a cada exposição suspeita |
| E8 | **Dependência e bolha informacional**: a pessoa deixa de ler as fontes e passa a ver o mercado só pelo filtro do modelo | Médio | Boletim curto, que não substitui a leitura de aprofundamento | Links das fontes no Telegram (como em E1); rotação de fontes (como em E2) |

### 3.1 Um caso real: o Reddit encerra o RSS em 13/11/2026

Durante esta análise, o Reddit anunciou o fim dos feeds RSS em **13 de novembro de 2026** e o encerramento da API pública em **março de 2027**. O motivo declarado é que o RSS virou um canal comum de raspagem em larga escala e abuso automatizado.

Isso afeta diretamente o projeto, porque o RSS é a rota usada para o Reddit. Duas respostas são possíveis:

- **Contornar o bloqueio** raspando o HTML do site. Isso contraria a decisão explícita da plataforma e seria exatamente o comportamento que motivou o bloqueio. **Descartada.**
- **Aceitar a perda da fonte** e substituí-la por fontes com acesso oficial. **Adotada.**

O sistema já está preparado para essa falha: o coletor trata cada fonte de forma independente, então, sem o Reddit, o boletim continua sendo gerado só com o Hacker News (até 5 notícias, em vez de 10). É um exemplo de robustez técnica que serve a uma decisão ética: respeitar a vontade de quem é dono dos dados.

## 4. IA responsável

### 4.1 Situação da regulação no Brasil

O Brasil ainda não tem lei específica de IA em vigor. O PL 2338/2023, o marco legal da inteligência artificial, foi aprovado no Senado em 10/12/2024 e, em novembro de 2026, segue na Câmara dos Deputados, aguardando o parecer do relator na comissão especial. A votação prevista para o primeiro semestre de 2026 não aconteceu, e o relator indicou que ela ficaria para depois das eleições de outubro.

O texto aprovado no Senado classifica os sistemas por risco. As áreas de alto risco citadas são, por exemplo, saúde, educação, crédito, recrutamento, segurança pública e infraestruturas críticas. Um boletim informativo de uso pessoal não se enquadra nessas categorias. Mesmo assim, o projeto adota as práticas que o texto exige de forma geral: transparência sobre o uso de IA, possibilidade de supervisão humana e responsabilização pelo funcionamento.

### 4.2 Princípios de IA responsável no projeto

| Princípio | Como aparece no Boletim IA |
|---|---|
| **Transparência** | A documentação declara que o conteúdo é gerado por IA, e o uso de assistentes de IA no desenvolvimento é declarado na entrega |
| **Robustez e segurança** | Tratamento de erros em duas camadas, fila contra concorrência, detecção de loop no áudio e de troca de idioma no roteiro |
| **Privacidade** | Processamento local, minimização, retenção implementada |
| **Justiça e diversidade** | Ponto fraco declarado: fontes pouco diversas (risco E2), com proposta de correção |
| **Supervisão humana** | A autora ouve o boletim e decide o que aprofundar; nenhuma decisão automática afeta terceiros |
| **Responsabilização** | Auditoria de cada execução no banco; histórico de mudanças no git |
| **Sustentabilidade** | Modelos pequenos rodando localmente: estimativa de 0,13 kWh por mês (notebook de ~60 W, ~4 min por dia), sem data center dedicado |

## 5. Implicações sociais

**Efeitos positivos**

- **Acesso.** Um sistema gratuito, local e sem chave de API mostra que estudantes e pequenos projetos conseguem usar IA generativa sem orçamento de nuvem.
- **Acessibilidade.** O formato em áudio atende pessoas com baixa visão, dislexia ou pouco tempo de tela, e permite consumir informação em deslocamento.
- **Soberania sobre os dados.** Nenhum dado é enviado a provedores de IA, o que reduz a dependência de grandes plataformas.

**Riscos se o sistema for usado em escala**

- **Desinformação.** Um boletim publicado para muitas pessoas multiplica cada alucinação (risco E1). Para uso público, a revisão humana antes da publicação deixa de ser opcional.
- **Concentração de agenda.** Quem escolhe as fontes escolhe o que o público vê. Com fontes pouco diversas (risco E2), o boletim reforça uma visão única do mercado.
- **Trabalho.** A curadoria automática compete com o trabalho de curadores e jornalistas de tecnologia. O uso responsável é complementar esse trabalho, citando e direcionando para as fontes originais, e não substituí-lo.
- **Relação com as plataformas.** O caso do Reddit (item 3.1) mostra que a coleta automatizada em massa leva plataformas a fechar acessos que antes eram abertos para todos, inclusive para usos legítimos e pequenos. Respeitar limites e termos de uso protege também o ecossistema.

## 6. Resumo: o que está feito e o que fica proposto

| Ação | Situação |
|---|---|
| Processamento local de coleta, LLM e voz | Implementado |
| Coleta sem autor (minimização) | Implementado |
| Política de retenção (30 dias / 12 meses) com modo de simulação | Implementado |
| Token fora do código, verificado no histórico do git | Implementado |
| Auditoria de cada pedido e execução | Implementado |
| Respeito ao limite de requisições das fontes | Implementado |
| Não contornar o fim do RSS do Reddit | Decidido |
| Links das fontes originais junto com o áudio | Proposto |
| Fontes mais diversas, incluindo brasileiras | Proposto |
| Remover nomes de usuário do texto do Reddit | Proposto (perde efeito com o fim do RSS) |
| Aviso de voz sintética, para uso público | Proposto |

## Referências

- Lei nº 13.709/2018 (LGPD), arts. 4º, 6º, 7º, 16 e 46. Texto compilado: <https://www.tce.rn.gov.br/as/Ouvidoria/Legislação/Lei_137092018_compilado_LGPD.pdf>
- PL 2338/2023, situação na Câmara (monitoramento de 12/11/2026): <https://monitor.lcfconsulting.com.br/proposicoes/pl-2338-2023/>
- Bairo Gonzalez, "Bill 2338/2023: where Brazil's AI framework stands in 2026" (out/2026): <https://bairogonzalez.com/en/in-the-world/ia/pl-2338-brazil-ai-legal-framework-2026/>
- Exame, "Marco legal para uso da inteligência artificial segue em tramitação" (dez/2025): <https://exame.com/esferabrasil/marco-legal-para-uso-da-inteligencia-artificial-segue-em-tramitacao/>
- TechWyse, "Reddit Ends RSS Feeds on November 13 and Shuts Public API by March 2027" (01/10/2026): <https://www.techwyse.com/news/social-media/reddit-rss-feeds-ending-public-api-shutdown-2027>
