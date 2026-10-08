# Conhecimento oficial, validação e fine-tuning — estado técnico

## Objetivo e distinções que não podem ser confundidas

1. **Documentação:** regras verificáveis e resumidas a partir de material
   oficial do Google Sheets, com IDs de fontes e condições explícitas.
2. **RAG:** fatos selecionados enviados somente após revisão e autorização.
   Melhora o acesso do modelo à informação, **sem alterar seus pesos**.
3. **Fine-tuning LoRA:** otimização de parâmetros de um modelo pré-treinado
   com um conjunto supervisionado licenciado/revisado. Só pode ser
   considerado concluído após execução efetiva, exportação e avaliação.
4. **Motor determinístico:** confere que propostas se referem a evidências
   locais, mas não garante equivalência de fórmulas nem aceleração.

No estado atual o Qwen 3.5 4B **NÃO FOI fine-tuned** pelo SheetOpt.
Nenhuma planilha do usuário é usada no conjunto de treinamento.

## Regras versionadas com fontes do Google

As regras ficam em `src/sheetopt/knowledge/rules.json`, com:
- afirmação técnica concisa (`claim`), categoria, termos de recuperação;
- condições necessárias para testar qualquer transformação (`requires`);
- risco default, ID de fonte, link oficial;
- validação de unicidade, tamanho e domínio na leitura.

A versão inicial cobre: SUMIFS, condições e curingas, QUERY e tipos
mistos/cabeçalhos, referências abertas, funções voláteis e atualização,
cadeias de dependências, importação entre arquivos, LET e chamadas à API.

As descrições são resumos editoriais, **não cópias integrais das páginas**.
A fonte primária e suas eventuais mudanças devem ser verificadas sempre.
A lista **não corresponde à documentação inteira do Google Sheets** e
não autoriza substituições automáticas.

Fontes principais:
- https://support.google.com/docs/answer/12159115?hl=pt-BR
- https://support.google.com/docs/answer/3093343?hl=pt-BR
- https://support.google.com/docs/answer/3238496?hl=en-GB
- https://support.google.com/docs/answer/3093583?hl=pt-BR
- https://support.google.com/docs/answer/13190535?hl=pt-BR
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet
- https://developers.google.com/workspace/sheets/api/guides/batch

## Análise estrutural e verificador de evidências

O `parser/structure.py` faz reconhecimento conservador de
SUMIFS/COUNTIFS, parênteses, argumentos, cadeias entre aspas e referências
de colunas inteiras. Isso **não é um parser/AST completo** e não gera
transformações. A implementação marca expressões não suportadas como
incompletas em vez de tentar escrever novas fórmulas.

`ai/evidence_gate.py` atua *depois* da inferência e não confia em
avaliações escritas pelo próprio modelo. Exemplos:
- contagem de NOW/TODAY do documento inteiro NÃO valida recomendações
  de funções voláteis em uma aba selecionada;
- uma referência aberta vista na amostra suporta investigação, mas
  exige política de crescimento e benchmark em cópia;
- SUMIFS → QUERY continua risco alto até checagem de tipos, critérios,
  vazios, datas, curingas, erros e valores comparados;
- se não houver evidência específica, a proposta é bloqueada como
  `needs_evidence`. Mesmo `review_only` não aprova transformações.

As etiquetas são incluídas na interface e nos relatórios JSON/PDF.

## Pipeline de preparo para treinamento supervisionado

Para preparar um conjunto **inicial** livre de dados de clientes:

```powershell
cd "C:\Users\colov\Desktop\sheetopt"
.\.venv\Scripts\Activate.ps1
python -m sheetopt.training.dataset --output-dir .\artifacts\sheets-sft
```

Arquivos locais:
- `train.jsonl` — exemplos de supervisão referenciando afirmações oficiais;
- `eval.jsonl` — conjunto separado por ID de regra;
- `manifest.json` — proveniência, contagens e status de treinamento.

O pequeno corpus inicial **é apenas material preparatório**, não comprova
generalização. O validador do treino EXIGE pelo menos 100 registros revisados
no treinamento, 15 na avaliação, nenhuma regra sobreposta, origem oficial,
licenciamento/conteúdo aprovado e autorização de uso da GPU.
Dados adicionais precisam ser criados e revisados por pessoas,
respeitando direitos de uso do material e sem incluir dados corporativos.
A avaliação deverá abranger perguntas adversariais, casos ambíguos,
idiomas/locais, métricas de fidelidade e conformidade e regressões.
Dividir por ID de regra reduz vazamento entre treino e avaliação, mas
não substitui avaliação em documentos/casos novos.

## Fine-tuning real (fora do hardware de inferência do usuário)

O treinamento opcional, com atualizações reais dos pesos do adaptador,
fica em `src/sheetopt/training/train_lora.py`. Ele não é chamado
automaticamente pela interface, CI ou inicialização do Docker.
Se houver corpus expandido, permissões adequadas e GPU suficiente:

```bash
python -m sheetopt.training.train_lora \
  --data-dir artifacts/sheets-sft \
  --output-dir artifacts/sheets-lora \
  --allow-gpu-training \
  --approved-content-license
```

**Não execute com o seed inicial:** ele é bloqueado pelo verificador
de qualidade mínima. O treino depende de pacotes opcionais (Unsloth,
Transformers v5, datasets, TRL e PyTorch) e deve ocorrer em um
ambiente separado com aproximadamente 10 GB ou mais de VRAM para o
Qwen 3.5 4B BF16 LoRA (a memória exata depende de sequência/batch).
O Unsloth **desaconselha QLoRA 4-bit** para Qwen3.5.
A RTX 3050 4 GB usada para inferência não é suficiente para
esse treinamento. Não se cria custo de GPU/cloud sem decisão do usuário.

Referência: https://unsloth.ai/docs/models/qwen3.5/fine-tune

Após treino é necessário avaliar o modelo-base e o adaptado no mesmo
conjunto *holdout* e em casos de fórmulas reais devidamente anonimizados,
verificando as propostas individualmente, erros de fonte, validade JSON
e riscos. Só depois de uma avaliação aprovada um modelo ajustado pode
ser exportado para GGUF/Ollama e configurado opcionalmente no SheetOpt.

## Próximas entregas importantes

- Expandir o catálogo além dos fatos iniciais, **com revisão e licenças**.
- Criar corpus de fórmulas sintéticas com casos-limite e ground truth
  executado em cópias de Sheets; revisão humana obrigatória.
- Implementar AST completo de Sheets, plano de rewrite por regras e
  verificação de resultados em cópias com medição de latência adequada.
- Construir benchmarks de generalização antes e depois do LoRA.
- Manter sempre a opção 100% determinística sem dependência de IA.

**Estado atual:** melhorias de fundamentação e infraestrutura de
fine-tuning; nenhum modelo foi efetivamente treinado nesta entrega.
