/** Agent 实体 — 对齐后端 AgentConfigItem */
export interface Agent {
  id: string;
  name: string;
  agent_type: string;
  system_prompt: string;
  model_name: string;
  temperature: number;
  is_active: boolean;
  created_at: string;
}

/** 创建 Agent 请求 — 对齐后端 CreateAgentRequest */
export interface CreateAgentRequest {
  name: string;
  agent_type: string;
  system_prompt: string;
  model_name?: string;
  temperature?: number;
  max_tokens?: number;
  tools?: string[];
}

/** 更新 Agent 请求 — 对齐后端 UpdateAgentRequest */
export interface UpdateAgentRequest {
  name?: string;
  agent_type?: string;
  system_prompt?: string;
  model_name?: string;
  temperature?: number;
  max_tokens?: number;
  tools?: string[];
  is_active?: boolean;
}
