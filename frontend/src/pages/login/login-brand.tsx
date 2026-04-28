import { useEffect, useState } from "react";
import { Film, Play, Layers, Palette } from "lucide-react";

const FEATURES = [
  { icon: Play, label: "AI 智能脚本生成，多风格适配" },
  { icon: Layers, label: "分镜与拍摄清单自动输出" },
  { icon: Palette, label: "专业级后期制作建议" },
];

export function LoginBrand() {
  const [active, setActive] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setActive((i) => (i + 1) % FEATURES.length), 3500);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="relative flex h-full flex-col justify-between overflow-hidden bg-zinc-900 p-10 lg:p-14">
      {/* 背景纹理 */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 25% 30%, rgba(255,255,255,0.8) 1px, transparent 1px), radial-gradient(circle at 75% 70%, rgba(255,255,255,0.8) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />

      {/* 顶部 */}
      <div className="relative z-10">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/[0.08]">
            <Film className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-white">ClipFlow</h1>
            <p className="text-[11px] text-zinc-500">Professional Video Creation</p>
          </div>
        </div>

        <div className="mt-12">
          <h2 className="text-3xl font-bold leading-tight text-white lg:text-4xl lg:leading-tight">
            专业级
            <br />
            视频创作工作台
          </h2>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-zinc-400">
            从选题策划到成片输出，AI 驱动每一个创作环节。
            脚本、分镜、拍摄清单、后期方案 — 一站式完成。
          </p>
        </div>
      </div>

      {/* 中间 — 亮点 */}
      <div className="relative z-10 space-y-4">
        {FEATURES.map(({ icon: Icon, label }, i) => (
          <div
            key={label}
            className="flex items-center gap-3 transition-all duration-500"
            style={{
              opacity: active === i ? 1 : 0.5,
              transform: active === i ? "translateX(6px)" : "translateX(0)",
            }}
          >
            <span
              className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors duration-500"
              style={{
                backgroundColor: active === i ? "rgba(255,255,255,0.15)" : "rgba(255,255,255,0.06)",
              }}
            >
              <Icon className="h-4 w-4 text-white" />
            </span>
            <span
              className="text-sm transition-colors duration-500"
              style={{ color: active === i ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.5)" }}
            >
              {label}
            </span>
          </div>
        ))}
      </div>

      {/* 底部 */}
      <div className="relative z-10 flex items-center justify-between">
        <p className="text-xs text-zinc-600">v0.2.0 · Plan + ReAct Engine</p>
        <div className="flex gap-1.5">
          {FEATURES.map((_, i) => (
            <button
              key={i}
              onClick={() => setActive(i)}
              className="h-1 rounded-full transition-all duration-300"
              style={{
                width: active === i ? 20 : 6,
                backgroundColor: active === i ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.15)",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
