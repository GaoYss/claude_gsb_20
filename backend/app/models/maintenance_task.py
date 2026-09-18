"""养护任务模型。"""

from ..constants import TASK_PRIORITY, TASK_STATUS, TASK_TYPE
from ..extensions import db
from ..utils.dates import format_date, format_datetime, today
from .mixins import TimestampMixin

OPEN_STATUSES = ("pending", "in_progress")

# 手动状态流转的合法路径（前置状态 -> 允许推进的目标状态）。
# 主流程：待执行 → 进行中 → 已完成/已取消；进行中可退回待执行，
# 已完成可撤销回进行中（整改复检），已取消为终态不允许再变更。
# 养护记录联动引起的状态推算不受此表约束，但同样会写入流转日志。
TASK_STATUS_TRANSITIONS = {
    "pending": ("in_progress", "cancelled"),
    "in_progress": ("pending", "completed", "cancelled"),
    "completed": ("in_progress",),
    "cancelled": (),
}


class MaintenanceTask(TimestampMixin, db.Model):
    """养护任务登记：一次养护作业的计划与执行状态。"""

    __tablename__ = "maintenance_task"

    id = db.Column(db.Integer, primary_key=True)
    task_no = db.Column(db.String(32), nullable=False, unique=True, index=True)
    green_space_id = db.Column(
        db.Integer, db.ForeignKey("green_space.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = db.Column(db.String(128), nullable=False)
    task_type = db.Column(db.String(32), nullable=False, index=True)
    plan_date = db.Column(db.Date, nullable=False, index=True)
    priority = db.Column(db.String(16), nullable=False, default="medium", index=True)
    executor = db.Column(db.String(64))
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    description = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)

    green_space = db.relationship("GreenSpace", back_populates="tasks", lazy="joined")
    records = db.relationship(
        "MaintenanceRecord",
        back_populates="task",
        order_by="MaintenanceRecord.record_date.desc(), MaintenanceRecord.id.desc()",
    )
    status_logs = db.relationship(
        "MaintenanceTaskStatusLog",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="MaintenanceTaskStatusLog.id",
    )

    @property
    def is_overdue(self):
        """未完成且计划日期早于今天即为逾期。"""

        return self.status in OPEN_STATUSES and self.plan_date < today()

    def to_dict(self, detail=False):
        data = {
            "id": self.id,
            "task_no": self.task_no,
            "green_space_id": self.green_space_id,
            "green_space": self.green_space.to_brief() if self.green_space else None,
            "title": self.title,
            "task_type": self.task_type,
            "task_type_label": TASK_TYPE.label(self.task_type),
            "plan_date": format_date(self.plan_date),
            "priority": self.priority,
            "priority_label": TASK_PRIORITY.label(self.priority),
            "executor": self.executor,
            "status": self.status,
            "status_label": TASK_STATUS.label(self.status),
            "allowed_status": list(TASK_STATUS_TRANSITIONS.get(self.status, ())),
            "completed_at": format_datetime(self.completed_at),
            "is_overdue": self.is_overdue,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
        if detail:
            data["description"] = self.description
        return data
