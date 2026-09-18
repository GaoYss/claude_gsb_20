"""养护任务状态流转日志模型。"""

from ..constants import TASK_STATUS
from ..extensions import db
from ..utils.dates import format_datetime
from .mixins import utcnow

# 状态变更来源：manual 手动操作（含编辑任务），auto 养护记录联动推算
SOURCE_LABELS = {"manual": "手动操作", "auto": "记录联动"}


class MaintenanceTaskStatusLog(db.Model):
    """任务状态每次变化的流水，按 id 升序即为状态变化顺序。"""

    __tablename__ = "maintenance_task_status_log"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status = db.Column(db.String(16))  # 任务登记时为 None
    to_status = db.Column(db.String(16), nullable=False)
    source = db.Column(db.String(16), nullable=False, default="manual")
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    task = db.relationship("MaintenanceTask", back_populates="status_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "from_status": self.from_status,
            "from_status_label": TASK_STATUS.label(self.from_status) if self.from_status else None,
            "to_status": self.to_status,
            "to_status_label": TASK_STATUS.label(self.to_status),
            "source": self.source,
            "source_label": SOURCE_LABELS.get(self.source, self.source),
            "note": self.note,
            "created_at": format_datetime(self.created_at),
        }
