import { useEffect } from "react";
import { useTenantStore } from "@/stores";

export function useTenant() {
  const store = useTenantStore();

  useEffect(() => {
    if (!store.tenant && !store.isLoading) {
      store.fetchTenant();
    }
    if (!store.usage && !store.isLoading) {
      store.fetchUsage();
    }
  }, []);

  return store;
}
