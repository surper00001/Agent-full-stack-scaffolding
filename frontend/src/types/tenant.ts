/** 租户信息 */
export interface Tenant {
  id: string;
  name: string;
  plan: "free" | "pro" | "enterprise";
  status: "active" | "suspended";
  memberCount: number;
  createdAt: string;
}

/** Token 用量概览 */
export interface TokenUsage {
  quota: number;
  used: number;
  dailyUsage: DailyUsage[];
  byAgent: AgentUsage[];
  recentRecords: UsageRecord[];
  comparedToLastMonth: number; // 百分比变化，正数增长
}

export interface DailyUsage {
  date: string;
  count: number;
}

export interface AgentUsage {
  agentName: string;
  count: number;
  percentage: number;
}

export interface UsageRecord {
  date: string;
  tokens: number;
  agentName: string;
}
