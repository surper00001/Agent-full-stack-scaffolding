import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, Zap } from "lucide-react";
import { useSkillStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const DEFAULT_CODE = `def execute(input_data: dict) -> dict:
    """
    Skill 入口函数。
    接收 input_data，返回处理结果 dict。
    """
    # TODO: 实现你的 Skill 逻辑
    return {"result": "Hello from Skill!", "input": input_data}
`;

export default function NewSkillPage() {
  const navigate = useNavigate();
  const { createSkill } = useSkillStore();

  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState(DEFAULT_CODE);
  const [category, setCategory] = useState("custom");
  const [securityLevel, setSecurityLevel] = useState("low");
  const [requiresSandbox, setRequiresSandbox] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!name.trim() || !displayName.trim()) {
      setError("请填写 Skill 名称和显示名称");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const skill = await createSkill({
        name: name.trim().toLowerCase().replace(/\s+/g, "_"),
        display_name: displayName.trim(),
        description: description.trim(),
        code,
        category,
        security_level: securityLevel,
        requires_sandbox: requiresSandbox,
      });
      navigate(`/admin/skills/${skill.id}`);
    } catch (err) {
      setError((err as Error).message || "创建失败");
      setSaving(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      {/* Breadcrumb */}
      <Button variant="ghost" onClick={() => navigate("/admin/skills")}>
        <ArrowLeft className="w-4 h-4 mr-2" />← 返回列表
      </Button>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Zap className="w-6 h-6 text-emerald-600" />
          新建 Skill
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          创建一个 AI 可调用的能力单元。Skill 将在沙箱环境中运行。
        </p>
      </div>

      {error && (
        <div className="p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Basic Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">基本信息</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">
                Skill 名称 <span className="text-red-500">*</span>
              </label>
              <Input
                placeholder="如: file_reader"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                英文标识符，用于系统调用
              </p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">
                显示名称 <span className="text-red-500">*</span>
              </label>
              <Input
                placeholder="如: 文件读取器"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                用户可见的名称
              </p>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">功能描述</label>
            <Input
              placeholder="简述 Skill 的功能..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">分类</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full border rounded-md px-3 py-2 text-sm bg-background"
              >
                <option value="custom">🔧 自定义</option>
                <option value="file">📄 文件处理</option>
                <option value="shell">💻 Shell 命令</option>
                <option value="network">🌐 网络请求</option>
                <option value="knowledge">📚 知识库</option>
                <option value="meta">🔄 元 Skill</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">安全级别</label>
              <select
                value={securityLevel}
                onChange={(e) => setSecurityLevel(e.target.value)}
                className="w-full border rounded-md px-3 py-2 text-sm bg-background"
              >
                <option value="low">低 — 只读操作</option>
                <option value="medium">中 — 有限写入</option>
                <option value="high">高 — 网络访问</option>
                <option value="critical">关键 — 完整系统访问</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">沙箱模式</label>
              <select
                value={requiresSandbox ? "yes" : "no"}
                onChange={(e) => setRequiresSandbox(e.target.value === "yes")}
                className="w-full border rounded-md px-3 py-2 text-sm bg-background"
              >
                <option value="yes">需要沙箱</option>
                <option value="no">无需沙箱（只读）</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Code */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">源代码</CardTitle>
        </CardHeader>
        <CardContent>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="w-full h-64 font-mono text-sm p-4 border rounded-md bg-muted/30 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            spellCheck={false}
          />
          <p className="text-xs text-muted-foreground mt-2">
            入口函数为 <code className="bg-muted px-1 rounded">def execute(input_data: dict) -&gt; dict</code>
          </p>
        </CardContent>
      </Card>

      {/* Submit */}
      <div className="flex justify-end gap-3">
        <Button variant="outline" onClick={() => navigate("/admin/skills")}>
          取消
        </Button>
        <Button onClick={handleSubmit} disabled={saving}>
          <Save className="w-4 h-4 mr-2" />
          {saving ? "创建中..." : "创建 Skill"}
        </Button>
      </div>
    </div>
  );
}
