# 1. Conhecimento especializado do Google Sheets

## Objetivo
A IA deve fundamentar hipóteses de otimização em documentação verificável, sem depender somente de memória paramétrica. O SheetOpt traz 8 referências oficiais de Google Sheets e Google Sheets API, com trechos interpretativos criados para o projeto (não cópias integrais das páginas).

## Implementação
- `src/sheetopt/knowledge/sources.json`: catálogo versionado (ID, categoria, URL oficial, palavras-chave, orientação e data).
- `src/sheetopt/knowledge/retrieval.py`: recuperação lexical determinística, offline e sem embeddings, até 4 referências por diagnóstico, priorizadas por funções e regras PERF.
- `src/sheetopt/ai/packet.py`: adiciona `knowledge_sources` ao pacote de contexto visualizado pelo usuário antes do consentimento.
- `GET /v1/knowledge` e `POST /v1/knowledge/search`: catálogo e busca no servidor local (autenticados).
- As citações da IA só podem referenciar IDs existentes no pacote. Documentação é evidência para raciocínio, nunca autorização para escrever.

## Fontes e cuidados de interpretação
1. **Cálculos repetidos e dependências:** https://support.google.com/docs/answer/11468464?hl=en — subexpressões compartilhadas e volatilidade.
2. **Referências abertas:** https://support.google.com/docs/answer/12159115?hl=en — colunas inteiras podem ampliar trabalho; nunca limitar intervalos sem política de crescimento.
3. **LET:** https://support.google.com/docs/answer/13190535?hl=pt-BR — expressões vinculadas calculadas uma vez, dentro do escopo.
4. **QUERY:** https://support.google.com/docs/answer/3093343?hl=pt-BR — tipos mistos podem ser convertidos em NULL segundo o tipo majoritário; cabeçalhos importam.
5. **SUMIFS:** https://support.google.com/docs/answer/3238496?hl=pt — critérios conjuntivos, intervalos compatíveis, números/datas.
6. **SUMIF:** https://support.google.com/docs/answer/3093583?hl=pt-BR — curingas e operadores que podem mudar a equivalência frente ao agrupamento.
7. **Sheets values API:** https://developers.google.com/workspace/sheets/api/guides/values — fórmulas, tipos e operações em lote.
8. **Sheets batchUpdate:** https://developers.google.com/workspace/sheets/api/guides/batchupdate — alterações estruturais, formatação e escrita transacional em lote.

## Evolução planejada
Não existe índice vetorial, atualização automática da documentação nem navegação na web pelo modelo. Antes de chamar o mecanismo de *RAG semântico*, adicionar ingestão versionada, embeddings locais com testes de recuperação, revogação de fontes, datas de vigência e avaliações de respostas fundamentadas. O catálogo atual é uma base de RAG lexical documentado.

## Critérios de aceitação
Busca local sem requisições HTTP externas; links de fonte válidos; citações inventadas descartadas; trechos com limites; nenhuma fórmula/dado do usuário indexado automaticamente. Ver `tests/test_ai_knowledge_evidence.py`.
