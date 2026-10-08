# Modelos locais recomendados e instalação no Windows

## Seleção para a máquina atual
Ambiente informado: Windows 10 64-bit, Intel Xeon E5-2680 v4 (14 núcleos/28 threads), 32 GB RAM, NVIDIA RTX 3050 ~4 GB VRAM.

**Primeira escolha: `qwen3.5:4b`.** Na biblioteca oficial do Ollama, ~3,3–4,0 GB de download conforme variante. Memória real de inferência inclui KV cache/overheads: pode ultrapassar 4 GB VRAM e recorrer ao CPU. Bom compromisso para análise conceitual e JSON estruturado; qualidade e velocidade só se confirmam com testes reais nesta máquina.

**Plano B velocidade:** `qwen3.5:2b`, menor e mais rápido, mas menos consistente em raciocínio difícil.
**Plano B código:** `qwen2.5-coder:7b`, ~4,7 GB de pesos quantizados e mais uso de RAM/CPU nesta GPU; é útil para comparar propostas de fórmulas, não a primeira opção para interface responsiva.
Não escolher 30B+ com esse hardware para testes interativos.

Fontes: https://ollama.com/library/qwen3.5 ; https://ollama.com/library/qwen2.5-coder ; https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx

## Instalação passo a passo (PowerShell, Windows)
1. Baixe e instale o Ollama em https://ollama.com/download. Abra um novo PowerShell.
2. Confira `ollama --version`.
3. Baixe `ollama pull qwen3.5:4b`.
4. Execute `ollama run qwen3.5:4b` e teste uma explicação breve; digite `/bye` para sair.
5. Confira os modelos disponíveis com `ollama list` e a API na máquina com `curl.exe http://localhost:11434/api/tags`.
6. Para conectar o SheetOpt, configure o servidor Ollama para ser alcançado pelo Docker. No Windows, feche a instância Ollama da bandeja antes de alterar `OLLAMA_HOST`. Em um PowerShell com sessão somente de teste: `$env:OLLAMA_HOST = "0.0.0.0:11434"` seguido de `ollama serve` (desde que não exista outro servidor rodando). Para manter, configure uma variável de ambiente do usuário e reinicie Ollama.
7. **Segurança:** escutar em `0.0.0.0` potencialmente expõe a API na rede. Restrinja o acesso à rede local/Docker usando regras de firewall, não faça port-forward público e não execute modelos sensíveis sem proteção de rede.
8. No diretório do SheetOpt rode `docker compose up -d --build`. Na interface, configure provedor **Local**, URL `http://host.docker.internal:11434/v1`, modelo `qwen3.5:4b`, chave vazia, e salve.
9. Em **IA contextual**, selecione uma aba, clique em **Investigar contexto local (sem IA)** e **Visualizar contexto que será enviado**. Confirme que o destino exibido é `host.docker.internal`. Marque consentimento e use **Gerar propostas com IA**.
10. Se houver timeout, confira se Ollama ainda está rodando, `curl.exe http://localhost:11434/api/tags`, o firewall e o acesso de `host.docker.internal` pelo container. Use `docker compose logs --tail=80 sheetopt` para erros genéricos, sem compartilhar tokens.

## Parâmetros iniciais
Use poucos milhares de tokens de contexto real, embora o modelo anuncie capacidade máxima muito maior. O backend do SheetOpt envia pacotes compactos de até 16 mil caracteres; janela teórica não é meta de consumo. JSON mode e `reasoning_effort=none` são configurados na chamada ao Ollama compatível para respostas mais rápidas e estruturadas. Se o modelo produzir JSON inválido, a aplicação rejeita a sugestão sem modificar nada. O timeout atual de modelo é ~65 segundos, podendo ser insuficiente para CPU-only; esse é um limite a medir e tornar configurável.

## Critérios de comparação
Teste o mesmo diagnóstico e as mesmas fontes nas duas opções. Registre: tempo de resposta, sucesso de JSON válido, referências oficiais coerentes, quantidade de alucinações, relevância das 5 propostas e consistência de resultados em 3 execuções. **Não use a nota atribuída pelo próprio modelo como medição de qualidade.**
