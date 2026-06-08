/** 模型定价 (USD per 1M tokens) */
export const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  "deepseek-chat": { input: 0.27, output: 1.10 },
  "deepseek-reasoner": { input: 0.55, output: 2.19 },
  "deepseek-v3": { input: 0.27, output: 1.10 },
  "gpt-4o": { input: 2.50, output: 10.00 },
  "gpt-4o-mini": { input: 0.15, output: 0.60 },
  "gpt-4-turbo": { input: 10.00, output: 30.00 },
  "claude-3-opus": { input: 15.00, output: 75.00 },
  "claude-3-sonnet": { input: 3.00, output: 15.00 },
  "claude-3-haiku": { input: 0.25, output: 1.25 },
  "claude-sonnet-4-6": { input: 3.00, output: 15.00 },
  "claude-haiku-4-5": { input: 0.25, output: 1.25 },
  "default": { input: 1.00, output: 4.00 },
};

/**
 * 根据 prompt_tokens + completion_tokens 估算费用
 * @param modelName 模型名称（匹配 pricing 表，未匹配用 default）
 * @param promptTokens 输入 token 数
 * @param completionTokens 输出 token 数
 * @returns USD 金额
 */
export function estimateCost(
  modelName: string,
  promptTokens: number,
  completionTokens: number,
): number {
  const pricing = MODEL_PRICING[modelName] ?? MODEL_PRICING["default"];
  return (
    (promptTokens / 1_000_000) * pricing.input +
    (completionTokens / 1_000_000) * pricing.output
  );
}

/**
 * 格式化费用为人类可读字符串
 */
export function formatCost(cost: number): string {
  if (cost >= 1) return `$${cost.toFixed(2)}`;
  if (cost >= 0.01) return `$${cost.toFixed(3)}`;
  if (cost >= 0.001) return `$${cost.toFixed(4)}`;
  return `$${cost.toExponential(2)}`;
}

/**
 * 从 TokenUsageStats 估算费用
 */
export function estimateCostFromUsage(
  modelName: string,
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  },
): number {
  return estimateCost(modelName, usage.prompt_tokens, usage.completion_tokens);
}

/** 模型显示名称映射 */
export const MODEL_DISPLAY_NAMES: Record<string, string> = {
  "deepseek-chat": "DeepSeek Chat",
  "deepseek-reasoner": "DeepSeek Reasoner",
  "deepseek-v3": "DeepSeek V3",
  "gpt-4o": "GPT-4o",
  "gpt-4o-mini": "GPT-4o Mini",
  "gpt-4-turbo": "GPT-4 Turbo",
  "claude-3-opus": "Claude 3 Opus",
  "claude-3-sonnet": "Claude 3 Sonnet",
  "claude-3-haiku": "Claude 3 Haiku",
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-haiku-4-5": "Claude Haiku 4.5",
};

export function getModelDisplayName(modelName: string): string {
  return MODEL_DISPLAY_NAMES[modelName] ?? modelName;
}
