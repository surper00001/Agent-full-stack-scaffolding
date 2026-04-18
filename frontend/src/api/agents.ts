import client from "./client";
import type {
  Agent,
  ApiResponse,
  CreateAgentRequest,
  PaginatedResponse,
  PaginationParams,
  UpdateAgentRequest,
} from "@/types";

const PATH = "/agents";

/** 获取Agent列表（分页） */
export async function getAgents(
  params?: PaginationParams,
): Promise<ApiResponse<PaginatedResponse<Agent>>> {
  const { data } = await client.get(PATH, { params });
  return data;
}

/** 获取单个Agent */
export async function getAgent(id: string): Promise<ApiResponse<Agent>> {
  const { data } = await client.get(`${PATH}/${id}`);
  return data;
}

/** 创建Agent */
export async function createAgent(
  payload: CreateAgentRequest,
): Promise<ApiResponse<Agent>> {
  const { data } = await client.post(PATH, payload);
  return data;
}

/** 更新Agent */
export async function updateAgent(
  id: string,
  payload: UpdateAgentRequest,
): Promise<ApiResponse<Agent>> {
  const { data } = await client.patch(`${PATH}/${id}`, payload);
  return data;
}

/** 删除Agent */
export async function deleteAgent(id: string): Promise<void> {
  await client.delete(`${PATH}/${id}`);
}
