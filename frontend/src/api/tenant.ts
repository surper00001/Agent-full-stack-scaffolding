import client from "./client";
import type { ApiResponse, Tenant, TokenUsage } from "@/types";

const PATH = "/tenant";

export async function getTenant(): Promise<ApiResponse<Tenant>> {
  const { data } = await client.get(PATH);
  return data;
}

export async function getTokenUsage(days = 30): Promise<ApiResponse<TokenUsage>> {
  const { data } = await client.get(`${PATH}/usage`, { params: { days } });
  return data;
}
