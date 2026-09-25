"""汇流箱管理业务规则：状态流转、支路异常定位、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "combiner"
REQUIRED_FIELDS = ["汇流箱编号", "接入组串数", "直流电压"]
OPTIONAL_FIELDS = ["输出电流", "防雷模块状态", "所属方阵", "安装位置", "运行状态"]
STATUS_ORDER = ["待巡检", "正常", "支路异常", "已更换"]
ACTION_RULES = {"确认正常": "正常", "登记支路异常": "支路异常", "更换设备": "已更换"}
NEGATIVE_ACTIONS = ["登记支路异常"]

ABNORMAL_STATUS = "支路异常"
# 直流电压正常区间（V）：超出区间的设备在列表与详情里单独着色。
DC_VOLTAGE_MIN = 500.0
DC_VOLTAGE_MAX = 1500.0
# 没有接入组串数的设备也要出现在定位结果里，并说明原因。
MISSING_STRINGS_REASON = "未登记接入组串数，无法按组串规模排序，已按运行状态与直流电压参与定位"
UNKNOWN_SPD_STATUS = "未登记"


def _to_float(value: Any) -> float | None:
    """把接入组串数、直流电压这类可数值字段转成 float；转不了就返回 None。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_branches(value: Any) -> list[int]:
    """把「3、7」「3,7」或列表统一成升序支路号列表，无法识别的条目直接丢弃。"""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).replace("、", ",").split(",")
    branches: list[int] = []
    for item in items:
        try:
            branch = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if branch > 0 and branch not in branches:
            branches.append(branch)
    return sorted(branches)


def _voltage_overflow(row: dict[str, Any]) -> bool:
    voltage = _to_float(row.get("直流电压"))
    return voltage is not None and not DC_VOLTAGE_MIN <= voltage <= DC_VOLTAGE_MAX


def _voltage_deviation(row: dict[str, Any]) -> float:
    """电压超出正常区间的距离，用于定位排序；区间内或缺测记 0。"""
    voltage = _to_float(row.get("直流电压"))
    if voltage is None:
        return 0.0
    if voltage < DC_VOLTAGE_MIN:
        return DC_VOLTAGE_MIN - voltage
    if voltage > DC_VOLTAGE_MAX:
        return voltage - DC_VOLTAGE_MAX
    return 0.0


def _locate_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """定位排序：支路异常置顶，电压越限其次，再按接入组串数从多到少、电压偏离从大到小。"""
    status_rank = 0 if row.get("status") == ABNORMAL_STATUS else 1
    voltage_rank = 0 if _voltage_overflow(row) else 1
    strings = _to_float(row.get("接入组串数"))
    strings_rank = -strings if strings is not None else float("inf")
    return (status_rank, voltage_rank, strings_rank, -_voltage_deviation(row), str(row.get("汇流箱编号") or ""))


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用的展示口径：防雷模块状态、异常支路号、电压越限、定位说明保持一致。"""
    item = dict(row)
    item["异常支路号"] = _parse_branches(row.get("异常支路号"))
    item["电压越限"] = _voltage_overflow(row)
    item["防雷模块状态"] = str(row.get("防雷模块状态") or "").strip() or UNKNOWN_SPD_STATUS
    item["定位说明"] = "" if _to_float(row.get("接入组串数")) is not None else MISSING_STRINGS_REASON
    return item


class CombinerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        locate: bool = False,
        arrays: list[str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("汇流箱编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if arrays:
            rows = [row for row in rows if str(row.get("所属方阵") or "").strip() in arrays]
        if locate:
            rows = self._locate(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_present(row) for row in rows[start:start + size]], total

    def _locate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """支路异常定位：排序后按汇流箱编号去重，跨方阵的同一台设备只保留一条。"""
        ordered = sorted(rows, key=_locate_key)
        seen: set[str] = set()
        located: list[dict[str, Any]] = []
        for row in ordered:
            key = str(row.get("汇流箱编号") or "").strip() or f"#{row.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            located.append(row)
        return located

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        entry["异常支路号"] = _parse_branches(values.get("异常支路号"))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _present(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"汇流箱 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于汇流箱管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        values = values or {}
        message = f"汇流箱已{action}"
        if action == "登记支路异常":
            branches = _parse_branches(values.get("异常支路号"))
            if branches:
                entry["异常支路号"] = branches
            existing = _parse_branches(entry.get("异常支路号"))
            if existing:
                message = f"汇流箱已登记支路异常，异常支路号：{'、'.join(str(branch) for branch in existing)}"
            else:
                message = "汇流箱已登记支路异常，未提供异常支路号，可重新登记并补充支路号"
        elif action == "确认正常":
            entry["异常支路号"] = []
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _present(entry), message
