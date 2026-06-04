# =============================================================================
# Harness Engineering — Sandbox 执行镜像
# =============================================================================
# 用途：AI 生成的 Skill 代码在此镜像中隔离执行
# 特点：
#   - 最小化 Python 3.12 镜像 + 常用依赖预装（加速冷启动）
#   - 非 root 用户执行（sandboxuser uid=1000）
#   - /workspace 为代码挂载点，/tmp 为临时文件区
#   - 无网络访问能力（运行时通过 --network=none 控制）
#
# 构建：
#   cd sandbox
#   docker build -t harness-sandbox:latest .
#
# 或在 WSL2 内：
#   wsl bash -c "cd /mnt/c/.../sandbox && docker build -t harness-sandbox:latest ."
# =============================================================================

FROM python:3.12-slim

LABEL org.harness.sandbox=true
LABEL org.harness.version="1.0"
LABEL description="Harness Engineering AI Skill 隔离执行沙箱"

# ── 安全配置 ──
# 创建非 root 用户
RUN groupadd -r sandboxgroup -g 1000 \
    && useradd -r -g sandboxgroup -u 1000 -m -s /bin/bash sandboxuser

# 工作目录
RUN mkdir -p /workspace /tmp/sandbox \
    && chown -R sandboxuser:sandboxgroup /workspace /tmp/sandbox

# ── 预装依赖（加速 Skill 首次执行，避免每次都 pip install） ──
# 分层策略：大包先装，小包后装，利用 Docker 层缓存
RUN pip install --no-cache-dir \
    # 核心库（几乎所有 Skill 都会用）
    requests==2.32.3 \
    httpx==0.28.1 \
    pydantic==2.10.4 \
    # 数据处理
    pandas==2.2.3 \
    numpy==2.2.1 \
    # 格式处理
    pyyaml==6.0.2 \
    python-dotenv==1.0.1 \
    beautifulsoup4==4.12.3 \
    lxml==5.3.0 \
    # 日期工具
    python-dateutil==2.9.0 \
    pytz==2024.2 \
    # 工具类
    httpx[http2]==0.28.1 \
    tenacity==9.0.0 \
    # JSON 增强
    orjson==3.10.13 \
    # 模板引擎
    jinja2==3.1.5

# ── 安全加固 ──
# 移除不必要的系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 创建只读标记文件（运行时配合 --read-only 挂载）
RUN touch /.sandbox_ready

# ── 切换到非 root 用户 ──
USER sandboxuser
WORKDIR /workspace

# 默认入口：执行注入的 Skill 代码
# 运行时通过 -v 挂载代码文件到 /workspace/exec.py
# docker run --rm --network=none -v /tmp/sandbox_xxx:/workspace harness-sandbox python exec.py
ENTRYPOINT ["python", "exec.py"]
