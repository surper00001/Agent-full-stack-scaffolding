import { useEffect, useCallback } from "react";
import { useAgentStore } from "@/stores";
import type { CreateAgentRequest, UpdateAgentRequest } from "@/types";

/**
 * Agent列表Hook — 自动加载并提供CRUD操作
 */
export function useAgents() {
  const store = useAgentStore();

  useEffect(() => {
    store.fetchAgents();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    agents: store.agents,
    total: store.total,
    isLoading: store.isLoading,
    error: store.error,
    refresh: useCallback(() => store.fetchAgents(), [store]),
    createAgent: useCallback(
      (payload: CreateAgentRequest) => store.createAgent(payload),
      [store],
    ),
    updateAgent: useCallback(
      (id: string, payload: UpdateAgentRequest) =>
        store.updateAgent(id, payload),
      [store],
    ),
    deleteAgent: useCallback(
      (id: string) => store.deleteAgent(id),
      [store],
    ),
  };
}

/**
 * 单个Agent Hook — 按ID加载
 */
export function useAgent(id: string | undefined) {
  const store = useAgentStore();

  useEffect(() => {
    if (id) store.fetchAgent(id);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    agent: store.currentAgent,
    isLoading: store.isLoading,
    error: store.error,
    refresh: useCallback(() => id && store.fetchAgent(id), [id, store]),
  };
}
