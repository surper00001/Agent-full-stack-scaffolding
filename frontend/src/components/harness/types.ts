/** Harness 组件共享类型 */

// 重新导出 skill 类型以方便使用
export type {
  Skill,
  SkillDetail,
  SkillTestResult,
  CreateSkillRequest,
  UpdateSkillRequest,
} from "@/types/skill";

/** 技能生命周期状态 */
export type SkillStatus =
  | "draft"
  | "testing"
  | "pending_review"
  | "approved"
  | "rejected"
  | "published"
  | "active"
  | "deprecated"
  | "archived";

/** 安全级别 */
export type SecurityLevel = "low" | "medium" | "high" | "critical";

/** 沙箱网络模式 */
export type SandboxNetwork = "none" | "internal" | "whitelist" | "full";

/** 安全扫描结果 */
export interface SecurityScanData {
  passed: boolean;
  score: number;
  findings: {
    severity: "info" | "warning" | "error" | "critical";
    line: number;
    message: string;
    rule: string;
  }[];
}
