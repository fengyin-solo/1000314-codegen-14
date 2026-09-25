"""汇流箱管理接口：维护汇流箱，覆盖确认正常、登记支路异常、更换设备等动作，并提供支路异常定位。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.combiner import CombinerService

router = APIRouter(prefix="/api/combiner", tags=["汇流箱管理"])

service = CombinerService()

LIST_FIELDS = ["汇流箱编号", "接入组串数", "直流电压", "输出电流", "防雷模块状态", "所属方阵", "安装位置", "运行状态"]
STATUSES = ["待巡检", "正常", "支路异常", "已更换"]


def _parse_arrays(arrays: str | None) -> list[str] | None:
    """把「一号方阵,二号方阵」解析成方阵列表；空值返回 None 表示不限方阵。"""
    if not arrays:
        return None
    items = [item.strip() for item in arrays.replace("，", ",").split(",") if item.strip()]
    return items or None


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按汇流箱编号检索"),
    status: str | None = Query(default=None, description="待巡检、正常、支路异常、已更换"),
    locate: bool = Query(default=False, description="开启支路异常定位：支路异常置顶、按接入组串数与直流电压排序"),
    arrays: str | None = Query(default=None, description="跨方阵定位：方阵名称逗号分隔，留空为全部方阵；同一台设备只显示一次"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按汇流箱编号与状态过滤汇流箱管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        locate=locate,
        arrays=_parse_arrays(arrays),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出汇流箱管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "combiner", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条汇流箱明细；与列表共用同一套展示口径，防雷模块状态等字段保持一致。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"汇流箱 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条汇流箱，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="汇流箱已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条汇流箱执行确认正常、登记支路异常、更换设备；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
