import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  User,
  Shield,
  Mail,
  Phone,
  Calendar,
  Lock,
  Check,
  X,
  Edit3,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import * as authApi from "@/api/auth";
import { cn } from "@/lib/utils";

export default function ProfilePage() {
  const navigate = useNavigate();
  const { user, isAdmin, initAuth } = useAuthStore();

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 pb-8">
      {/* 返回按钮 */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors -ml-1"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        返回
      </button>

      {/* 头像卡片 */}
      <Card>
        <CardContent className="flex items-center gap-5 py-6">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary ring-4 ring-primary/5">
            <span className="text-2xl font-bold">{user.username.charAt(0).toUpperCase()}</span>
          </div>
          <div className="min-w-0 space-y-0.5">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold truncate">{user.username}</h1>
              {isAdmin && (
                <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
                  管理员
                </span>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              {isAdmin ? "系统管理员" : "普通用户"}
              <span className="mx-1.5">·</span>
              {user.is_verified ? (
                <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                  <Check className="h-3 w-3" /> 已验证
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <X className="h-3 w-3" /> 未验证
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground/60">
              注册于 {new Date(user.created_at).toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* 基本信息 */}
      <ProfileInfoSection user={user} onUpdated={initAuth} />

      {/* 修改密码 */}
      <PasswordSection />
    </div>
  );
}

/** 个人信息编辑区 */
function ProfileInfoSection({
  user,
  onUpdated,
}: {
  user: NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
  onUpdated: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<"username" | "email" | "phone" | null>(null);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const startEdit = (field: "username" | "email" | "phone") => {
    setEditing(field);
    setValue(user[field] || "");
    setError("");
  };

  const cancelEdit = () => {
    setEditing(null);
    setError("");
  };

  const handleSave = async () => {
    if (!editing) return;
    setSaving(true);
    setError("");
    try {
      await authApi.updateProfile({ [editing]: value || undefined });
      await onUpdated();
      setEditing(null);
    } catch (err: unknown) {
      setError((err as { userMessage?: string })?.userMessage || (err as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Shield className="h-4 w-4 text-muted-foreground" />
          个人信息
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {/* 用户名 */}
        <InfoRow
          label="用户名"
          icon={User}
          value={user.username}
          editing={editing === "username"}
          editValue={editing === "username" ? value : ""}
          onChange={setValue}
          onEdit={() => startEdit("username")}
          onSave={handleSave}
          onCancel={cancelEdit}
          saving={saving && editing === "username"}
        />

        {/* 邮箱 */}
        <InfoRow
          label="邮箱"
          icon={Mail}
          value={user.email || "未设置"}
          muted={!user.email}
          editing={editing === "email"}
          editValue={editing === "email" ? value : ""}
          onChange={setValue}
          onEdit={() => startEdit("email")}
          onSave={handleSave}
          onCancel={cancelEdit}
          saving={saving && editing === "email"}
          placeholder="输入邮箱地址"
        />

        {/* 手机号 */}
        <InfoRow
          label="手机号"
          icon={Phone}
          value={user.phone || "未设置"}
          muted={!user.phone}
          editing={editing === "phone"}
          editValue={editing === "phone" ? value : ""}
          onChange={setValue}
          onEdit={() => startEdit("phone")}
          onSave={handleSave}
          onCancel={cancelEdit}
          saving={saving && editing === "phone"}
          placeholder="输入手机号"
        />

        {/* 只读字段 */}
        <ReadOnlyRow label="角色" value={user.role === "admin" ? "管理员" : "普通用户"} icon={Shield} />
        <ReadOnlyRow
          label="账号状态"
          value={user.is_active ? "正常" : "已禁用"}
          icon={Check}
          valueClass={user.is_active ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}
        />
        <ReadOnlyRow
          label="注册时间"
          value={new Date(user.created_at).toLocaleString("zh-CN")}
          icon={Calendar}
        />

        {error && (
          <p className="text-xs text-destructive text-right mt-2">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** 单行信息（可编辑） */
function InfoRow({
  label,
  icon: Icon,
  value,
  muted,
  editing,
  editValue,
  onChange,
  onEdit,
  onSave,
  onCancel,
  saving,
  placeholder,
}: {
  label: string;
  icon: typeof User;
  value: string;
  muted?: boolean;
  editing: boolean;
  editValue: string;
  onChange: (v: string) => void;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  placeholder?: string;
}) {
  return (
    <div className="flex items-center gap-3 py-3 border-b last:border-b-0 group">
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="text-sm text-muted-foreground shrink-0 w-14">{label}</span>

      {editing ? (
        <div className="flex flex-1 items-center gap-2">
          <Input
            value={editValue}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="h-8 text-sm"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") onSave();
              if (e.key === "Escape") onCancel();
            }}
          />
          <Button size="sm" onClick={onSave} disabled={saving} className="h-8 gap-1 text-xs">
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            保存
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving} className="h-8 text-xs">
            取消
          </Button>
        </div>
      ) : (
        <>
          <span className={cn("flex-1 text-sm font-medium", muted && "text-muted-foreground/50")}>
            {value}
          </span>
          <button
            onClick={onEdit}
            className="shrink-0 rounded p-1 text-muted-foreground/30 opacity-0 transition-all hover:text-foreground group-hover:opacity-100"
            title={`编辑${label}`}
          >
            <Edit3 className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  );
}

/** 只读信息行 */
function ReadOnlyRow({
  label,
  value,
  icon: Icon,
  valueClass,
}: {
  label: string;
  value: string;
  icon: typeof User;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center gap-3 py-3 border-b last:border-b-0">
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="text-sm text-muted-foreground shrink-0 w-14">{label}</span>
      <span className={cn("flex-1 text-sm font-medium", valueClass)}>{value}</span>
    </div>
  );
}

/** 修改密码区 */
function PasswordSection() {
  const [form, setForm] = useState({ oldPassword: "", newPassword: "", confirmPassword: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (form.newPassword !== form.confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    if (form.newPassword.length < 6) {
      setError("新密码长度至少 6 位");
      return;
    }

    setSaving(true);
    try {
      await authApi.changePassword({
        old_password: form.oldPassword,
        new_password: form.newPassword,
      });
      setSuccess("密码修改成功");
      setForm({ oldPassword: "", newPassword: "", confirmPassword: "" });
    } catch (err: unknown) {
      setError((err as { userMessage?: string })?.userMessage || (err as Error).message || "修改失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Lock className="h-4 w-4 text-muted-foreground" />
          修改密码
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">旧密码</label>
            <Input
              type="password"
              placeholder="输入当前密码"
              value={form.oldPassword}
              onChange={(e) => setForm({ ...form, oldPassword: e.target.value })}
              className="h-9"
              required
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">新密码</label>
              <Input
                type="password"
                placeholder="至少 6 位"
                value={form.newPassword}
                onChange={(e) => setForm({ ...form, newPassword: e.target.value })}
                className="h-9"
                required
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">确认新密码</label>
              <Input
                type="password"
                placeholder="再次输入新密码"
                value={form.confirmPassword}
                onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
                className="h-9"
                required
              />
            </div>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
          {success && <p className="text-xs text-emerald-600 dark:text-emerald-400">{success}</p>}

          <Button type="submit" disabled={saving} className="gap-2">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            修改密码
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
