# 3. Evidência determinística, histórico e aprendizagem por casos

## Objetivo
A IA gera hipóteses; o motor determinístico executa testes; somente resultados verificados podem alimentar recomendações futuras. Nunca apresentar `impact=high` do modelo como ganho medido.

## Implementado neste marco
- `src/sheetopt/evidence/trials.py` registra de forma local, criptografada e append-only os resultados **reais do validador de uma célula da cópia**: `validated_cell_only`, `rejected`, `reverted`, `manual_review_required`, ou resultado incerto.
- `GET /v1/evidence/trials`, autenticado, mostra o histórico com identificadores de cópia/candidato resumidos por SHA-256, sem fórmula, valor, Google ID nem chave.
- `src/sheetopt/evidence/benchmark.py` contém um avaliador **puro** de séries de tempos medidos, exigindo ao menos cinco amostras por versão, uso de mediana e equivalência declarada; ainda NÃO está conectado a cronometração real do Sheets.

**Estado real da aplicação:** nenhuma proposta da IA é executada. O validador experimental pode verificar só a célula-alvo; não prova dependências, formatos globais ou recálculo. Por isso todas as entradas atuais têm `performance_measured=false`, `equivalence_proven=false`, `merge_available=false` e ganho numérico `null`.

## Plano para benchmark real e comparação ampla
1. Snapshot da versão anterior, incluindo fórmula, valor efetivo, apresentação, validação, formatos, dependentes e hash de versão.
2. Criar clone de trabalho exclusivo por experimento e isolar editores/automação concorrentes.
3. Executar alterações com limites rígidos e sem mexer na original.
4. Recalcular explicitamente e aguardar estabilização; definir critérios de ausência de alterações e timeout.
5. Comparar todos os nós atingidos por caminhos de dependência, diferenças de tipos e erros, intervalos de matriz, datas, números e tolerância numérica explicitamente definida.
6. Medir tempo de **recálculo** (não apenas tempo de uma chamada HTTP) com no mínimo 5 execuções por variante, ordem A/B alternada, carregamento inicial equivalente, múltiplos tamanhos e execução em ambiente controlado.
7. Registrar mediana, variabilidade, condições, limites, regressões e taxa de falha; nunca confiar em uma única amostra.
8. Habilitar merge apenas quando houver prova de equivalência e ausência de conflitos com alterações feitas desde o snapshot original; exigir aceite humano.

## Aprendizado
Em etapa posterior, montar uma biblioteca local **somente de casos completos e auditáveis**, com regra, metadados anonimizados, hash da implementação, benchmarks e razão de validação/rejeição. O LLM recuperará casos históricos sem receber dados brutos, mas não alterará o critério de aprovação.

## Critérios de aceitação
Rejeições e rollback preservados; evidência não permite modificar o Sheets; modelo não escreve histórico; benchmark fictício não pode ser registrado como comprovado; replay de tentativa bloqueado.
