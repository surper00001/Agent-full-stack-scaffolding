# 租户管理

## 概览

管理员查看租户信息与 Token 用量，含可视化图表。

## 页面结构

```
/tenant
├── 租户信息卡片行（4张）
│   ├── 租户名称 + ID
│   ├── 成员数量
│   ├── 套餐计划
│   └── 状态标识
├── Token 用量区域
│   ├── 环形仪表盘（本月已用 / 总额度）
│   ├── 30 天日用量柱状图（SVG 自绘）
│   └── 用量趋势对比（较上月）
├── Agent 用量明细
│   └── 表格：Agent 名称 | 调用次数 | Token 消耗 | 占比条
└── 最近用量记录
    └── 表格：日期 | Token 数 | 主要 Agent
```

## 数据类型

```ts
interface Tenant {
  id: string
  name: string
  plan: "free" | "pro" | "enterprise"
  status: "active" | "suspended"
  memberCount: number
  createdAt: string
}

interface TokenUsage {
  total: number          // 总额度
  used: number           // 本月已用
  dailyUsage: { date: string; count: number }[]
  byAgent: { agentName: string; count: number; percentage: number }[]
  recentRecords: { date: string; tokens: number; agentName: string }[]
}
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/tenant | 获取租户详情 |
| GET | /api/v1/tenant/usage?days=30 | 获取 Token 用量数据 |

## 动画

- 卡片入场：staggered fadeInUp（每个卡片延迟 50ms）
- 数字滚动：AnimatedCounter 组件，ease-out 800ms
- 环形仪表盘：SVG stroke-dashoffset 动画 1s
- 柱状图：hover 时柱子变亮 + tooltip，初始从 0 生长动画
- 页面切换：整体 fade-in 200ms
- 数据加载：骨架屏

## 组件拆分

- `AnimatedCounter` — 数字递增动画
- `TokenGauge` — SVG 环形仪表盘
- `DailyBarChart` — 30 天柱状图
- `UsageTable` — 用量明细表
