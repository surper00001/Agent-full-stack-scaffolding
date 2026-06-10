"""
Skill 生命周期状态机。

状态流转：
    draft → testing → pending_review → approved → published → active
                                               ↓            ↓
                                          rejected     deprecated → archived

每个状态定义了合法操作和自动副作用（如更新 usage_count）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SkillStatus(StrEnum):
    """Skill 生命周期状态。"""
    DRAFT = "draft"
    TESTING = "testing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


# 状态转移规则：from → {to: guard_fn}
_STATE_TRANSITIONS: dict[SkillStatus, dict[SkillStatus, str | None]] = {
    SkillStatus.DRAFT: {
        SkillStatus.TESTING: "测试通过后进入测试状态",
        SkillStatus.PENDING_REVIEW: "直接提交审核",
        SkillStatus.ARCHIVED: "废弃草稿",
    },
    SkillStatus.TESTING: {
        SkillStatus.DRAFT: "测试失败，返回草稿",
        SkillStatus.PENDING_REVIEW: "测试通过，提交审核",
        SkillStatus.ARCHIVED: "放弃此版本",
    },
    SkillStatus.PENDING_REVIEW: {
        SkillStatus.APPROVED: "审核通过",
        SkillStatus.REJECTED: "审核拒绝",
    },
    SkillStatus.APPROVED: {
        SkillStatus.PUBLISHED: "发布上线",
        SkillStatus.ARCHIVED: "取消发布",
    },
    SkillStatus.REJECTED: {
        SkillStatus.DRAFT: "修改后重新提交",
        SkillStatus.ARCHIVED: "放弃",
    },
    SkillStatus.PUBLISHED: {
        SkillStatus.ACTIVE: "激活启用",
        SkillStatus.DEPRECATED: "标记为弃用",
        SkillStatus.ARCHIVED: "归档",
    },
    SkillStatus.ACTIVE: {
        SkillStatus.DEPRECATED: "标记为弃用",
        SkillStatus.PUBLISHED: "降级回已发布",
    },
    SkillStatus.DEPRECATED: {
        SkillStatus.ARCHIVED: "归档",
        SkillStatus.ACTIVE: "重新激活",
    },
    SkillStatus.ARCHIVED: {
        SkillStatus.DRAFT: "重新起草",  # 复活
    },
}


@dataclass
class LifecycleEvent:
    """生命周期事件记录。"""
    from_status: SkillStatus
    to_status: SkillStatus
    timestamp: float = field(default_factory=time.time)
    reason: str = ""
    triggered_by: str = ""  # "user" / "system" / "agent_id"


class SkillLifecycle:
    """
    Skill 生命周期状态机。

    使用方式：
        lc = SkillLifecycle(SkillStatus.DRAFT)
        lc.transition(SkillStatus.TESTING, reason="AI 生成完成")

        if lc.can_transition(SkillStatus.PUBLISHED):
            lc.transition(SkillStatus.PUBLISHED)
    """

    def __init__(self, initial: SkillStatus = SkillStatus.DRAFT) -> None:
        self._status = initial
        self._history: list[LifecycleEvent] = []

    @property
    def status(self) -> SkillStatus:
        return self._status

    @property
    def history(self) -> list[LifecycleEvent]:
        return list(self._history)

    @property
    def is_active(self) -> bool:
        return self._status == SkillStatus.ACTIVE

    @property
    def is_usable(self) -> bool:
        """Skill 当前是否可用。"""
        return self._status in (SkillStatus.PUBLISHED, SkillStatus.ACTIVE)

    @property
    def is_editable(self) -> bool:
        """代码是否可编辑。"""
        return self._status in (
            SkillStatus.DRAFT,
            SkillStatus.TESTING,
            SkillStatus.REJECTED,
        )

    def can_transition(self, target: SkillStatus) -> bool:
        """检查是否可以转换到目标状态。"""
        allowed = _STATE_TRANSITIONS.get(self._status, {})
        return target in allowed

    def get_allowed_transitions(self) -> dict[SkillStatus, str]:
        """获取当前状态允许的所有目标状态及说明。"""
        return dict(_STATE_TRANSITIONS.get(self._status, {}))

    def transition(
        self,
        target: SkillStatus,
        reason: str = "",
        triggered_by: str = "system",
    ) -> LifecycleEvent:
        """
        执行状态转换。

        Raises:
            ValueError: 非法状态转换
        """
        if not self.can_transition(target):
            allowed = list(self.get_allowed_transitions().keys())
            raise ValueError(
                f"不允许的状态转换: {self._status.value} → {target.value}。"
                f"允许: {[s.value for s in allowed]}"
            )

        event = LifecycleEvent(
            from_status=self._status,
            to_status=target,
            reason=reason,
            triggered_by=triggered_by,
        )
        self._history.append(event)
        self._status = target
        return event

    def force_transition(
        self,
        target: SkillStatus,
        reason: str = "管理员强制转换",
    ) -> LifecycleEvent:
        """强制状态转换（跳过守卫检查）。"""
        event = LifecycleEvent(
            from_status=self._status,
            to_status=target,
            reason=reason,
            triggered_by="admin",
        )
        self._history.append(event)
        self._status = target
        return event


# ── 标准工作流 ──

def get_approval_workflow(skip_testing: bool = False) -> list[SkillStatus]:
    """获取标准审批流程的状态列表。"""
    if skip_testing:
        return [
            SkillStatus.DRAFT,
            SkillStatus.PENDING_REVIEW,
            SkillStatus.APPROVED,
            SkillStatus.PUBLISHED,
            SkillStatus.ACTIVE,
        ]
    return [
        SkillStatus.DRAFT,
        SkillStatus.TESTING,
        SkillStatus.PENDING_REVIEW,
        SkillStatus.APPROVED,
        SkillStatus.PUBLISHED,
        SkillStatus.ACTIVE,
    ]


def get_auto_publish_workflow() -> list[SkillStatus]:
    """自动发布流程（跳过人工审核）。"""
    return [
        SkillStatus.DRAFT,
        SkillStatus.TESTING,
        SkillStatus.PUBLISHED,
        SkillStatus.ACTIVE,
    ]
