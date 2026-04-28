import { useEffect } from "react";
import { useTenantStore } from "@/stores";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { TenantInfoCards } from "./tenant-info-cards";
import { TokenUsageSection } from "./token-usage-section";
import { UsageByAgent } from "./usage-by-agent";
import { UsageHistory } from "./usage-history";

export default function TenantPage() {
  const { tenant, usage, isLoading, error, fetchTenant, fetchUsage } = useTenantStore();

  useEffect(() => {
    fetchTenant();
    fetchUsage();
  }, [fetchTenant, fetchUsage]);

  if (isLoading && !tenant) {
    return <LoadingSpinner size="lg" className="mt-24" />;
  }

  if (error && !tenant) {
    return (
      <div className="flex flex-col items-center justify-center mt-24 gap-3">
        <p className="text-muted-foreground">{error}</p>
        <button
          onClick={() => { fetchTenant(); fetchUsage(); }}
          className="text-sm text-primary hover:underline"
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader />

      {tenant && <TenantInfoCards tenant={tenant} />}

      {usage && (
        <>
          <SectionTitle title="Token 使用情况" />
          <TokenUsageSection usage={usage} />
          <div className="grid gap-4 lg:grid-cols-2">
            <UsageByAgent data={usage.byAgent} />
            <UsageHistory records={usage.recentRecords} />
          </div>
        </>
      )}

      {!usage && !isLoading && (
        <p className="text-sm text-muted-foreground text-center py-8">
          暂无用量数据
        </p>
      )}
    </div>
  );
}

function PageHeader() {
  return (
    <div>
      <h1 className="text-2xl font-bold">租户管理</h1>
      <p className="text-muted-foreground mt-1">查看租户信息与 Token 用量统计</p>
    </div>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <h2 className="text-lg font-semibold">{title}</h2>;
}
