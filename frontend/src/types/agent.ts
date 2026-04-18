/** Agent类型枚举 */
export type AgentType = "chat" | "tool_use" | "rag" | "multi_agent";

/** Agent状态 */
export type AgentStatus = "active" | "inactive" | "error";

/** Agent配置 */
export interface AgentConfig {
  temperature: number;
  max_tokens: number;
  model: string;
  system_prompt: string;
  tools: string[];
}

/** Agent实体 */
export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  type: AgentType;
  status: AgentStatus;
  config: AgentConfig;
  created_at: string;
  updated_at: string;
}

/** 创建Agent请求 */
export interface CreateAgentRequest {
  name: string;
  description: string;
  type: AgentType;
  config: Partial<AgentConfig>;
}

/** 更新Agent请求 */
export interface UpdateAgentRequest extends Partial<CreateAgentRequest> {
  status?: AgentStatus;
}
