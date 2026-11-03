# Delegação e uso estratégico de modelos

- Separe subagentes sempre que necessário para tarefas independentes, investigação de causas distintas ou uma revisão útil em paralelo.
- Mantenha tarefas curtas e etapas dependentes no agente principal quando delegar só aumentar contexto, espera e consumo.
- Para leitura, busca, conferência e mudanças simples, prefira Sol com esforço baixo (`low`).
- Para implementação delimitada, use Sol com esforço médio ou alto conforme a dificuldade.
- Para arquitetura, diagnóstico ou implementação complexa, use Sol com esforço extra alto (`xhigh`) ou outro modelo disponível mais adequado. Escale com base na necessidade observada.
- Ao selecionar outro modelo ou esforço, use `fork_turns="none"` e passe apenas objetivo, caminhos relevantes, restrições e resultado esperado.
- Defina a responsabilidade de cada agente; evite investigação duplicada, edições concorrentes nos mesmos arquivos e ações concorrentes no aparelho.
- Reavalie quantidade, esforço e consumo dos agentes entre as etapas. Conclua cada subtask quando houver resultado suficiente para integração.
- Preserve a qualidade e os testes necessários; economize com escopo e contexto adequados, sem omitir verificações relevantes.

O modelo deve ser escolhido entre os disponíveis na sessão. Esses critérios são uma política de execução; não pressupõem preços ou disponibilidade fixa.
