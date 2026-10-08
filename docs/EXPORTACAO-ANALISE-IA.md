# Exportação completa das análises da IA

## Objetivo
Permitir comparar os resultados do modelo com o diagnóstico real sem copiar
manualmente cada proposta. Exportar **somente uma execução concluída** da IA
em dois formatos: JSON auditável e PDF legível.

## Conteúdo
- Identificação da execução: horário UTC, modelo, provedor e destino (somente
  hostname; nunca endereço com credenciais).
- Números agregados do diagnóstico: abas, fórmulas e padrões.
- O **pacote exato** enviado ao modelo (inclusive fontes documentais recuperadas,
  estruturas de contexto e políticas de anonimização) e SHA-256 para integridade.
- Resumo integral retornado pelo modelo.
- Todas as propostas: título, justificativa, impacto hipotético, risco, abas
  apontadas, fontes alegadas e passos de validação.
- Informações adicionais requisitadas pelo modelo.
- Tempo de espera no navegador, quando disponível. **Não é benchmark**
  de processamento do Google Sheets.
- Indicação explícita de resultado não validado: sem prova de equivalência,
  sem cálculo de aceleração e sem alterações/merge.

## Como usar
Abra o SheetOpt, importe o diagnóstico, selecione contexto e modo, gere a
prévia e autorize a análise. Após a conclusão aparecerá **Baixar análise
completa**, com os botões **Exportar JSON completo** e **Exportar PDF
completo**. O PDF é processado por `POST /v1/reports/ai/pdf` no servidor
local; não requer chamadas a Google nem ao provedor de IA. O JSON é criado
no navegador a partir do objeto estruturado da resposta, sem scraping HTML.

## Cuidados e limitações
- As análises ficam na memória da página, e não são guardadas automaticamente
  em um histórico de IA. **Baixe os arquivos antes de atualizar o navegador**.
- Uma análise realizada **antes desta versão** não estará disponível
  retroativamente depois de recarregar a página.
- O contexto exportado poderá incluir nomes internos de abas e cabeçalhos caso
  a opção correspondente tenha sido autorizada. Inspecione o JSON antes de
  compartilhá-lo; o PDF incorpora o mesmo contexto no apêndice.
- As recomendações ainda são hipóteses do modelo. O arquivo não constitui
  validação nem autoriza edições da planilha original.
- O servidor verifica o SHA-256 do contexto enviado e restringe tamanho e
  formato dos campos antes de produzir o PDF.
- O PDF é obtido via endpoint autenticado de administração, sem gravação
  persistente no servidor.
