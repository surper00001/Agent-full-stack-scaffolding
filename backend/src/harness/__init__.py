"""
Harness Engineering 核心模块。

提供：
- HarnessTool 统一工具接口（Pydantic 校验）
- AbortSignal 可组合取消信号树
- StreamingToolExecutor 流式并行工具调度
- Skill Registry（DB-backed 热加载）
- WSL2 Docker 沙箱隔离
- 代码安全扫描
"""
