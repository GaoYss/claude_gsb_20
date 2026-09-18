"""养护任务接口测试。"""

from datetime import date, timedelta


def task_payload(space_id, **overrides):
    payload = {
        "green_space_id": space_id,
        "title": "行道树整形修剪",
        "task_type": "prune",
        "plan_date": "2026-03-10",
        "priority": "high",
        "executor": "绿化一班",
        "description": "疏枝整形，清理枯枝。",
    }
    payload.update(overrides)
    return payload


def test_create_task_generates_daily_code(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/maintenance-tasks", task_payload(space.id)), 201)
    assert data["task_no"] == f"MT-{date.today():%Y%m%d}-001"
    assert data["status"] == "pending"
    assert data["priority_label"] == "高"
    assert data["green_space"]["id"] == space.id


def test_create_task_validates_green_space(api):
    response = api.post("/api/v1/maintenance-tasks", task_payload(999))
    assert response.status_code == 422
    assert response.get_json()["data"] == {"green_space_id": "所选绿地不存在"}


def test_archived_green_space_rejects_new_task(api, make_space):
    space = make_space(status="archived")
    response = api.post("/api/v1/maintenance-tasks", task_payload(space.id))
    assert response.status_code == 409
    assert "已归档" in response.get_json()["message"]


def test_list_filters_by_status_type_and_overdue(api, make_space, make_task):
    space = make_space()
    make_task(space=space, task_type="prune", status="pending",
              plan_date=date.today() - timedelta(days=5))
    make_task(space=space, task_type="water", status="completed", plan_date=date(2026, 3, 10))

    assert api.data(api.get("/api/v1/maintenance-tasks", status="pending"))["meta"]["total"] == 1
    assert api.data(api.get("/api/v1/maintenance-tasks", task_type="water"))["meta"]["total"] == 1
    overdue = api.data(api.get("/api/v1/maintenance-tasks", overdue="true"))
    assert overdue["meta"]["total"] == 1
    assert overdue["items"][0]["is_overdue"] is True


def test_list_includes_record_progress(api, make_task, make_record):
    task = make_task()
    make_record(task=task, quality_result="qualified")
    make_record(task=task, quality_result="pending", record_date=date(2026, 3, 18))

    data = api.data(api.get("/api/v1/maintenance-tasks", green_space_id=task.green_space_id))
    assert data["items"][0]["progress"] == {"record_count": 2, "qualified_count": 1}


def test_status_transition_records_completed_at(api, make_task):
    task = make_task()
    data = api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status",
                              {"status": "in_progress"}))
    assert data["status"] == "in_progress"
    assert data["completed_at"] is None

    data = api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "completed"}))
    assert data["status"] == "completed"
    assert data["completed_at"] is not None

    # 撤销完成：已完成可退回进行中，完成时间清空
    data = api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status",
                              {"status": "in_progress"}))
    assert data["status"] == "in_progress"
    assert data["completed_at"] is None

    data = api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "cancelled"}))
    assert data["status"] == "cancelled"
    assert data["completed_at"] is None


def test_pending_task_cannot_complete_directly(api, make_task):
    task = make_task()
    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "completed"})
    assert response.status_code == 409
    assert "不能直接标记完成" in response.get_json()["message"]


def test_completed_task_cannot_be_cancelled(api, make_task):
    task = make_task(status="in_progress")
    api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "completed"}))
    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "cancelled"})
    assert response.status_code == 409
    assert "不能变更" in response.get_json()["message"]


def test_cancelled_task_is_terminal(api, make_task):
    task = make_task()
    data = api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "cancelled"}))
    assert data["status"] == "cancelled"
    assert data["allowed_status"] == []

    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "in_progress"})
    assert response.status_code == 409
    assert "已取消" in response.get_json()["message"]


def test_allowed_status_follows_state_machine(api, make_task):
    task = make_task()
    data = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))
    assert sorted(data["allowed_status"]) == ["cancelled", "in_progress"]


def test_status_logs_track_manual_changes_in_order(api, make_task):
    task = make_task()
    for status in ("in_progress", "completed", "in_progress", "cancelled"):
        api.data(api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": status}))

    logs = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))["status_logs"]
    assert [(log["from_status"], log["to_status"]) for log in logs] == [
        (None, "pending"),            # 任务登记
        ("pending", "in_progress"),
        ("in_progress", "completed"),
        ("completed", "in_progress"),
        ("in_progress", "cancelled"),
    ]
    assert all(log["source"] == "manual" for log in logs)
    assert logs[0]["note"] == "任务登记"
    assert logs[-1]["to_status_label"] == "已取消"


def test_record_sync_writes_auto_status_logs(api, make_task, make_record):
    task = make_task()
    record = make_record(task=task, quality_result="qualified")

    detail = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))
    assert detail["status"] == "completed"
    auto_logs = [log for log in detail["status_logs"] if log["source"] == "auto"]
    assert [(log["from_status"], log["to_status"]) for log in auto_logs] == [("pending", "completed")]
    assert auto_logs[0]["source_label"] == "记录联动"

    # 删除记录后任务回退待执行，同样留下联动日志
    api.data(api.delete(f"/api/v1/maintenance-records/{record.id}"))
    logs = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))["status_logs"]
    assert [(log["from_status"], log["to_status"]) for log in logs if log["source"] == "auto"] == [
        ("pending", "completed"),
        ("completed", "pending"),
    ]


def test_update_task_status_via_put_is_validated(api, make_task):
    task = make_task()
    payload = task_payload(task.green_space_id, status="completed")
    response = api.put(f"/api/v1/maintenance-tasks/{task.id}", payload)
    assert response.status_code == 409
    assert "不能直接标记完成" in response.get_json()["message"]

    data = api.data(api.put(f"/api/v1/maintenance-tasks/{task.id}",
                            task_payload(task.green_space_id, status="in_progress")))
    assert data["status"] == "in_progress"
    logs = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))["status_logs"]
    assert [(log["from_status"], log["to_status"]) for log in logs] == [
        (None, "pending"),
        ("pending", "in_progress"),
    ]


def test_update_task_without_status_keeps_current(api, make_task):
    task = make_task(status="in_progress")
    # task_payload 不含 status 字段，校验未传状态时不会触发流转
    data = api.data(api.put(f"/api/v1/maintenance-tasks/{task.id}",
                            task_payload(task.green_space_id)))
    assert data["status"] == "in_progress"


def test_cannot_complete_task_with_unqualified_record(api, make_task, make_record):
    task = make_task()
    make_record(task=task, quality_result="unqualified")
    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "completed"})
    assert response.status_code == 409
    assert "不合格" in response.get_json()["message"]


def test_status_payload_requires_valid_enum(api, make_task):
    task = make_task()
    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "done"})
    assert response.status_code == 422
    assert "status" in response.get_json()["data"]


def test_detail_returns_records_and_progress(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task, work_hours=6)
    make_replacement(record=record, quantity=24, unit_price=100)

    data = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))
    assert data["progress"]["record_count"] == 1
    assert data["progress"]["total_work_hours"] == 6.0
    assert data["progress"]["replacement_quantity"] == 24.0
    assert data["progress"]["replacement_amount"] == 2400.0
    assert data["records"][0]["record_no"].startswith("MR-")


def test_delete_task_requires_force_when_records_exist(api, make_task, make_record):
    task = make_task()
    make_record(task=task)
    response = api.delete(f"/api/v1/maintenance-tasks/{task.id}")
    assert response.status_code == 409

    data = api.data(api.delete(f"/api/v1/maintenance-tasks/{task.id}", force="true"))
    assert data == {"detached_records": 1}
    # 强制删除后养护记录保留，仅解除关联
    records = api.data(api.get("/api/v1/maintenance-records", unlinked="true"))
    assert records["meta"]["total"] == 1


def test_update_task_rejects_unknown_enum(api, make_task):
    task = make_task()
    response = api.put(f"/api/v1/maintenance-tasks/{task.id}",
                       task_payload(task.green_space_id, task_type="digging"))
    assert response.status_code == 422
