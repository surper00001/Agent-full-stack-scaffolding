/** Skill 实体 */
export interface Skill {
  id: string;
  tenant_id: string;
  name: string;
  display_name: string;
  description: string;
  version: string;
  category: string;
  skill_type: string;
  is_read_only: boolean;
  is_concurrency_safe: boolean;
  requires_sandbox: boolean;
  security_level: string;
  status: string;
  is_active: boolean;
  is_public: boolean;
  usage_count: number;
  avg_rating: number | null;
  author: string | null;
  created_at: string;
  updated_at: string;
}

/** Skill 详情（含代码） */
export interface SkillDetail extends Skill {
  code: string;
  code_hash: string | null;
  input_schema: string | null;
  output_schema: string | null;
  dependencies: string | null;
  requires_approval: boolean;
  sandbox_image: string | null;
  sandbox_cpu_limit: number | null;
  sandbox_memory_mb: number | null;
  sandbox_timeout_seconds: number | null;
  sandbox_network: string | null;
  test_results: string | null;
  security_scan_result: string | null;
  success_count: number;
  avg_duration_ms: number | null;
}

/** 创建 Skill 请求 */
export interface CreateSkillRequest {
  name: string;
  display_name: string;
  description: string;
  code: string;
  version?: string;
  category?: string;
  skill_type?: string;
  input_schema?: string;
  dependencies?: string[];
  is_read_only?: boolean;
  is_concurrency_safe?: boolean;
  requires_sandbox?: boolean;
  security_level?: string;
}

/** 更新 Skill 请求 */
export interface UpdateSkillRequest {
  display_name?: string;
  description?: string;
  code?: string;
  input_schema?: string;
  dependencies?: string[];
  is_read_only?: boolean;
  is_concurrency_safe?: boolean;
  requires_sandbox?: boolean;
  security_level?: string;
  is_active?: boolean;
  is_public?: boolean;
}

/** AI 生成 Skill 请求 */
export interface GenerateSkillRequest {
  requirement: string;
  category?: string;
  auto_test?: boolean;
  auto_publish?: boolean;
}

/** Skill 测试请求 */
export interface SkillTestRequest {
  input_data: Record<string, unknown>;
  timeout_seconds?: number;
}

/** Skill 测试结果 */
export interface SkillTestResult {
  success: boolean;
  output: unknown;
  error: string | null;
  duration_ms: number;
}

/** Skill 生成结果 */
export interface SkillGenerateResult {
  skill: SkillDetail;
  generated_code: string;
  tests_passed: boolean | null;
  scan_passed: boolean | null;
  warnings: string[];
}

/** Skill 生命周期状态颜色映射 */
export const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-200 text-gray-700",
  testing: "bg-blue-200 text-blue-700",
  pending_review: "bg-yellow-200 text-yellow-700",
  approved: "bg-green-200 text-green-700",
  rejected: "bg-red-200 text-red-700",
  published: "bg-indigo-200 text-indigo-700",
  active: "bg-emerald-200 text-emerald-700",
  deprecated: "bg-orange-200 text-orange-700",
  archived: "bg-gray-300 text-gray-500",
};

/** Skill 状态中文映射 */
export const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  testing: "测试中",
  pending_review: "待审核",
  approved: "已审核",
  rejected: "已拒绝",
  published: "已发布",
  active: "已激活",
  deprecated: "已弃用",
  archived: "已归档",
};
