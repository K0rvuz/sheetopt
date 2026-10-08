# SheetOpt — Arquitetura de IA e maturidade

## Filosofia
O SheetOpt é um sistema de otimização com **IA opcional e evidência determinística**. Modelo não recebe Google OAuth, chave de API, acesso direto à planilha nem função de escrita. O usuário conserva a infraestrutura e os dados no seu ambiente.

## Pipeline
```text
Google Sheets / diagnóstico JSON
          ↓
Inventário de fórmulas e grafo parcial por aba
          ↓
RAG lexical (catálogo oficial versionado)
          ↓
Investigação direcionada (overview/upstream/downstream/hotspots)
          ↓
Prévia exata do pacote + hash + consentimento
          ↓
Propostas estruturadas do modelo local/externo
          ↓
Revisão humana + regras determinísticas
          ↓
Experimento isolado na cópia + rollback
          ↓
Histórico real com nível de validação explícito
          ↓
[ FUTURO ] Benchmarks de recálculo e equivalência completa
          ↓
[ FUTURO ] Merge parcial com prova + aprovação
```

## Contratos e acesso
- Catálogo: `GET /v1/knowledge`, `POST /v1/knowledge/search`.
- Investigação sem rede: `POST /v1/ai/investigate`.
- Prévia sem modelo: `POST /v1/ai/preview` (pacote + SHA-256).
- Inferência após consentimento: `POST /v1/ai/suggest` (somente propostas).
- Registros de validação: `GET /v1/evidence/trials` (sem conteúdo bruto).
- Teste determinístico anterior: `POST /v1/optimizations/test` (clone gerenciado, uso único).

## Limites atuais e próximos passos
A recuperação é **lexical** e as fontes são curadas; embeddings, atualização automática e avaliação de RAG ficam para próxima evolução. Investigação é **manual e sobre contexto já disponível**; a IA ainda não requisita novas leituras no Google. O histórico registra **testes de célula**, não benchmark de desempenho. Todas as melhorias futuras precisam preservar a separação entre hipótese, evidência parcial e prova do comportamento integral da planilha.

Ver: [Conhecimento](01-CONHECIMENTO-RAG.md), [Investigação](02-INVESTIGACAO-CONTEXTUAL.md), [Evidências](03-EVIDENCIAS-E-BENCHMARK.md), [Modelos Windows](MODELOS-LOCAIS-WINDOWS.md).
