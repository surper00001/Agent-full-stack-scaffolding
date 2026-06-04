import client from "./client";
import type {
  CreateSkillRequest,
  GenerateSkillRequest,
  Skill,
  SkillDetail,
  SkillGenerateResult,
  SkillTestRequest,
  SkillTestResult,
  UpdateSkillRequest,
} from "@/types/skill";
import type { PaginatedData } from "@/types/api";

const BASE = "/skills";

/** 获取 Skill 列表 */
export async function getSkills(params?: {
  page?: number;
  page_size?: number;
  status?: string;
  category?: string;
}): Promise<{ data: PaginatedData<Skill> }> {
  const { data } = await client.get(BASE, { params });
  return data;
}

/** 获取 Skill 详情 */
export async function getSkill(id: string): Promise<{ data: SkillDetail }> {
  const { data } = await client.get(`${BASE}/${id}`);
  return data;
}

/** 创建 Skill */
export async function createSkill(
  payload: CreateSkillRequest
): Promise<{ data: SkillDetail }> {
  const { data } = await client.post(BASE, payload);
  return data;
}

/** 更新 Skill */
export async function updateSkill(
  id: string,
  payload: UpdateSkillRequest
): Promise<{ data: SkillDetail }> {
  const { data } = await client.put(`${BASE}/${id}`, payload);
  return data;
}

/** 删除 Skill */
export async function deleteSkill(id: string): Promise<void> {
  await client.delete(`${BASE}/${id}`);
}

/** 测试 Skill */
export async function testSkill(
  id: string,
  payload: SkillTestRequest
): Promise<{ data: SkillTestResult }> {
  const { data } = await client.post(`${BASE}/${id}/test`, payload);
  return data;
}

/** 发布 Skill */
export async function publishSkill(id: string): Promise<{ data: SkillDetail }> {
  const { data } = await client.post(`${BASE}/${id}/publish`);
  return data;
}

/** 弃用 Skill */
export async function deprecateSkill(id: string): Promise<{ data: SkillDetail }> {
  const { data } = await client.post(`${BASE}/${id}/deprecate`);
  return data;
}

/** 转换状态 */
export async function transitionSkill(
  id: string,
  targetStatus: string,
  reason?: string
): Promise<{ data: SkillDetail }> {
  const { data } = await client.post(
    `${BASE}/${id}/status/${targetStatus}`,
    null,
    { params: { reason } }
  );
  return data;
}

/** AI 生成 Skill */
export async function generateSkill(
  id: string,
  payload: GenerateSkillRequest
): Promise<{ data: SkillGenerateResult }> {
  const { data } = await client.post(`${BASE}/${id}/generate`, payload);
  return data;
}
