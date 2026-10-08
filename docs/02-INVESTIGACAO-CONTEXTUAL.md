# 2. Investigação contextual e escopo de autorização

## Disponível hoje
`POST /v1/ai/investigate` responde **somente com o relatório/contexto já disponível** e referências recuperadas. Nenhum pedido ao Google ou à IA é feito. O modo escolhido é incluído no pacote e a prévia é obrigatória antes de transmitir:
- `overview`: resumo do documento ou aba selecionada.
- `upstream`: quais abas são explicitamente referenciadas pela aba selecionada.
- `downstream`: quais outras abas referenciam a aba selecionada.
- `hotspots`: intervalos de alta frequência (diagnóstico, não benchmark).

No navegador, `IA contextual` permite selecionar a aba e o modo e clicar em **Investigar contexto local (sem IA)**. Apenas depois de **Visualizar contexto que será enviado**, ler a prévia exata, marcar consentimento e clicar em **Gerar propostas com IA** existe transmissão ao provedor configurado.

## Proteção de dados
O pacote usa aliases de abas por padrão, sem fórmulas, IDs de planilha e valores brutos; nomes e possíveis cabeçalhos exigem opt-in. A base de conhecimento oficial é pública, mas os metadados de contagem e estrutura do documento podem revelar funcionamento interno. Armazene/exporte apenas o necessário.

## Limites de completude
O contexto atual detecta apenas referências **A1 explícitas entre abas**. Não resolve referências locais célula-a-célula, intervalos nomeados, `INDIRECT`, `QUERY` dinâmicas, IMPORTRANGE ou dependências de saída de matrizes. O arquivo JSON antigo pode não ter o grafo completo e deve informar `diagnostic_only`.

O modelo **ainda não controla ferramentas** para ler intervalos/células extras no Google. O usuário precisa voltar ao diagnóstico completo para atualizar metadados. Próxima fase, sujeita a revisão de privacidade: ferramenta granular somente leitura, seleção explícita de planilha/aba/intervalo, limite de células e de tempo, resultados sanitizados, logging e novo consentimento por ampliação de escopo. Jamais permitir IDs e ranges livres enviados pelo modelo sem autorização.

## Fluxo para desenvolvimento do agente
(1) IA recebe resumo e fontes; (2) propõe uma solicitação de contexto na forma `sheet/range/purpose`; (3) backend valida contra limites e escopo autorizado; (4) usuário autoriza ampliação; (5) execução read-only; (6) reavalia hipótese; (7) oferece plano para ser validado no clone. Não permitir chamadas arbitrárias de URL, SQL, código Python ou escrita pelo agente.

## Critérios de aceitação
Os quatro modos não fazem chamadas externas; modos direcionais exigem aba; escopo selecionado e hash da prévia devem ser idênticos ao enviado; alteração de escopo invalida consentimento anterior.

## Leitura pontual de exemplos de fórmulas — nova etapa
A opção **Buscar amostras no Google (somente leitura)** pede autorização
explícita e escolhe no máximo 6 células dentre os endereços de exemplo dos
alertas da aba selecionada. A chamada usa somente Sheets API
`values.batchGet(valueRenderOption=FORMULA)`. Nenhuma célula ou planilha é
alterada, e nada é enviado ao modelo nessa operação.

O backend devolve somente **formas sanitizadas** das fórmulas,
substituindo literais textuais, constantes numéricas, nomes de abas e
identificadores desconhecidos. A sanitização é heurística: o usuário deve
inspecionar os exemplos antes de autorizar o envio ao modelo.
A caixa **Incluir amostras sanitizadas na consulta ao modelo** inicia
desmarcada. Mudá-la invalida a prévia anterior; é necessário aprovar uma nova.

O sistema diferencia explicitamente funções contadas no **documento inteiro**
das observações em **células de exemplo** da aba. Uma fórmula amostrada não
representa todas as fórmulas da aba nem prova equivalência.
Relatórios antigos, células alteradas e abas sem locais elegíveis podem
não oferecer exemplos. O modelo não recebe acesso livre à planilha.
