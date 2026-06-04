import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Play,
  RefreshCw,
  Save,
  Zap,
  Edit3,
  X,
  Code2,
  FlaskConical,
} from "lucide-react";
import { useSkillStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import {
  StatePipeline,
  SandboxCard,
  SecurityCard,
  MetricsCard,
} from "@/components/harness";
import { testSkill } from "@/api/skills";
import { cn } from "@/lib/utils";
import type { SkillTestResult } from "@/types/skill";

export default function SkillDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    currentSkill,
    isLoading,
    fetchSkill,
    updateSkill,
    transitionSkill,
  } = useSkillStore();

  // 编辑模式
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState("");
  const [desc, setDesc] = useState("");

  // 测试面板
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<SkillTestResult | null>(null);
  const [testInput, setTestInput] = useState("{}");
  const [testPanelOpen, setTestPanelOpen] = useState(false);

  // 加载
  useEffect(() => {
    if (id) fetchSkill(id);
  }, [id, fetchSkill]);

  useEffect(() => {
    if (currentSkill) {
      setCode(currentSkill.code);
      setDesc(currentSkill.description);
    }
  }, [currentSkill]);

  // ── 操作 ──

  const handleTransition = async (targetStatus: string) => {
    if (!id) return;
    await transitionSkill(id, targetStatus);
    fetchSkill(id);
  };

  const handleTest = async () => {
    if (!id) return;
    setTesting(true);
    setTestResult(null);
    setTestPanelOpen(true);
    try {
      let inputData: Record<string, unknown> = {};
      try {
        inputData = JSON.parse(testInput);
      } catch {
        inputData = { query: testInput };
      }
      const res = await testSkill(id, {
        input_data: inputData,
        timeout_seconds: 30,
      });
      setTestResult(res.data);
    } catch (err) {
      setTestResult({
        success: false,
        output: null,
        error: (err as Error).message,
        duration_ms: 0,
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!id) return;
    await updateSkill(id, { code, description: desc });
    setEditing(false);
  };

  const handleCancelEdit = () => {
    if (currentSkill) {
      setCode(currentSkill.code);
      setDesc(currentSkill.description);
    }
    setEditing(false);
  };

  // ── 渲染 ──

  if (isLoading || !currentSkill) return <LoadingSpinner />;

  const skill = currentSkill;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* ── 面包屑 + 标题栏 ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate("/admin/skills")}>
            <ArrowLeft className="w-4 h-4 mr-1" />← 返回
          </Button>
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-emerald-500" />
            <h1 className="text-xl font-bold">{skill.display_name}</h1>
            <code className="text-xs bg-muted px-2 py-0.5 rounded font-mono text-muted-foreground">
              {skill.name} v{skill.version}
            </code>
          </div>
        </div>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button variant="outline" size="sm" onClick={handleCancelEdit}>
                <X className="w-4 h-4 mr-1" />取消
              </Button>
              <Button size="sm" onClick={handleSave}>
                <Save className="w-4 h-4 mr-1" />保存
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              <Edit3 className="w-4 h-4 mr-1" />编辑代码
            </Button>
          )}
        </div>
      </div>

      {/* ── 生命周期状态机 ── */}
      <Card>
        <CardContent className="pt-4">
          <StatePipeline
            currentStatus={skill.status}
            onTransition={handleTransition}
          />
        </CardContent>
      </Card>

      {/* ── 主布局：左编辑区 + 右仪表盘 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* 左侧：描述 + 代码编辑器 (占 3 列) */}
        <div className="lg:col-span-3 space-y-6">
          {/* 功能描述 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">功能描述</CardTitle>
            </CardHeader>
            <CardContent>
              {editing ? (
                <Input
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="描述此 Skill 的功能、输入输出..."
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {skill.description || "暂无描述"}
                </p>
              )}
            </CardContent>
          </Card>

          {/* 源代码 */}
          <Card>
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <Code2 className="w-4 h-4" />
                源代码
              </CardTitle>
              <span className="text-[10px] text-muted-foreground font-mono">
                SHA256: {skill.code_hash?.slice(0, 16) ?? "-"}
              </span>
            </CardHeader>
            <CardContent>
              {editing ? (
                <textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="w-full h-96 font-mono text-sm p-4 border rounded-md bg-muted/30 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  spellCheck={false}
                />
              ) : (
                <pre className="text-sm font-mono p-4 rounded-md bg-muted/30 overflow-auto max-h-96 border">
                  <code>{skill.code}</code>
                </pre>
              )}
            </CardContent>
          </Card>

          {/* 沙箱测试面板 */}
          <Card>
            <CardHeader
              className="pb-2 flex flex-row items-center justify-between cursor-pointer"
              onClick={() => setTestPanelOpen(!testPanelOpen)}
            >
              <CardTitle className="text-sm flex items-center gap-2">
                <FlaskConical className="w-4 h-4 text-emerald-500" />
                沙箱测试
              </CardTitle>
              <Button variant="ghost" size="sm" className="text-xs">
                {testPanelOpen ? "收起 ▲" : "展开 ▼"}
              </Button>
            </CardHeader>
            {testPanelOpen && (
              <CardContent className="space-y-3">
                <div className="flex gap-2">
                  <Input
                    placeholder='测试输入 (JSON), 如 {"query": "hello"}'
                    value={testInput}
                    onChange={(e) => setTestInput(e.target.value)}
                    className="flex-1 font-mono text-sm"
                  />
                  <Button onClick={handleTest} disabled={testing}>
                    {testing ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-1" />
                    )}
                    测试
                  </Button>
                </div>
                {testResult && (
                  <div
                    className={cn(
                      "p-4 rounded-md border",
                      testResult.success
                        ? "bg-green-50 border-green-200"
                        : "bg-red-50 border-red-200"
                    )}
                  >
                    <div className="text-sm font-medium mb-1 flex items-center gap-2">
                      {testResult.success ? "✓ 测试通过" : "✗ 测试失败"}
                      <span className="text-muted-foreground text-xs font-normal">
                        ({testResult.duration_ms.toFixed(0)}ms)
                      </span>
                    </div>
                    {testResult.success ? (
                      <pre className="text-xs font-mono mt-2 whitespace-pre-wrap max-h-48 overflow-auto">
                        {typeof testResult.output === "string"
                          ? testResult.output
                          : JSON.stringify(testResult.output, null, 2)}
                      </pre>
                    ) : (
                      <pre className="text-xs font-mono mt-2 text-red-700 whitespace-pre-wrap max-h-48 overflow-auto">
                        {testResult.error}
                      </pre>
                    )}
                  </div>
                )}
              </CardContent>
            )}
          </Card>
        </div>

        {/* 右侧：仪表盘 (占 2 列) */}
        <div className="lg:col-span-2 space-y-4">
          {/* 沙箱环境 */}
          <SandboxCard
            image={skill.sandbox_image}
            cpuLimit={skill.sandbox_cpu_limit}
            memoryMb={skill.sandbox_memory_mb}
            timeoutSeconds={skill.sandbox_timeout_seconds}
            network={skill.sandbox_network}
            requiresSandbox={skill.requires_sandbox}
          />

          {/* 安全护栏 */}
          <SecurityCard
            securityLevel={skill.security_level}
            requiresApproval={skill.requires_approval}
            scanResult={skill.security_scan_result}
            allowedImports={skill.dependencies}
            isReadOnly={skill.is_read_only}
          />

          {/* 运行指标 */}
          <MetricsCard
            usageCount={skill.usage_count}
            successCount={skill.success_count}
            avgDurationMs={skill.avg_duration_ms}
            avgRating={skill.avg_rating}
            isConcurrencySafe={skill.is_concurrency_safe}
          />

          {/* 元信息 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">基本信息</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">ID</span>
                <code className="font-mono text-[10px]">{skill.id.slice(0, 8)}...</code>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">分类</span>
                <span className="capitalize">{skill.category}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">类型</span>
                <span>{skill.skill_type}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">作者</span>
                <span>{skill.author || "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">公开</span>
                <span>{skill.is_public ? "是" : "否"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">创建时间</span>
                <span>{new Date(skill.created_at).toLocaleDateString("zh-CN")}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
