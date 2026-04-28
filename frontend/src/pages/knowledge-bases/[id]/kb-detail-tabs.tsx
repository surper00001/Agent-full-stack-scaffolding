import { FileText, Search } from "lucide-react";

export type KBDetailTab = "documents" | "search";

interface KBDetailTabsProps {
  tab: KBDetailTab;
  onChange: (tab: KBDetailTab) => void;
}

export function KBDetailTabs({ tab, onChange }: KBDetailTabsProps) {
  const tabClass = (active: boolean) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      active
        ? "border-primary text-primary"
        : "border-transparent text-muted-foreground hover:text-foreground"
    }`;

  return (
    <div className="flex gap-1 border-b">
      <button type="button" onClick={() => onChange("documents")} className={tabClass(tab === "documents")}>
        <FileText className="inline h-4 w-4 mr-1" />
        文档
      </button>
      <button type="button" onClick={() => onChange("search")} className={tabClass(tab === "search")}>
        <Search className="inline h-4 w-4 mr-1" />
        检索
      </button>
    </div>
  );
}
