"""养护任务状态流转日志模型。"""

from ..constants import TASK_STATUS, TASK_STATUS_SOURCE
from ..extensions import db
from ..utils.dates import format_datetime
from .mixins import utcnow


class MaintenanceTaskStatusLog(db.Model):
    """任务状态流转留痕：登记、手动流转与记录联动各写一条，详情按时间正序展示。"""

    __tablename__ = "maintenance_task_status_log"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status = db.Column(db.String(16))  # 为空表示登记时的初始状态
    to_status = db.Column(db.String(16), nullable=False)
    source = db.Column(db.String(16), nullable=False, default="manual")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "from_status": self.from_status,
            "from_status_label": TASK_STATUS.label(self.from_status) if self.from_status else None,
            "to_status": self.to_status,
            "to_status_label": TASK_STATUS.label(self.to_status),
            "source": self.source,
            "source_label": TASK_STATUS_SOURCE.label(self.source),
            "created_at": format_datetime(self.created_at),
        }
