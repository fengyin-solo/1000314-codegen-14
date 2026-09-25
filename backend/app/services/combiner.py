"""汇流箱管理业务规则：状态流转、字段校验、支路异常定位与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "combiner"
REQUIRED_FIELDS = ["汇流箱编号", "接入组串数", "直流电压"]
STATUS_ORDER = ["待巡检", "正常", "支路异常", "已更换"]
ACTION_RULES = {"确认正常": "正常", "登记支路异常": "支路异常", "更换设备": "已更换"}
NEGATIVE_ACTIONS = []

# 直流母线电压正常区间（V），超出区间的设备在列表中单独着色提示。
VOLTAGE_MIN = 580.0
VOLTAGE_MAX = 860.0

# 防雷模块状态归一口径：列表与详情共用同一份映射，避免两处显示不一致。
SPD_NORMAL = {"正常", "良好", "ok", "正常（已检测）"}
SPD_FAULT = {"故障", "异常", "失效", "损坏", "告警"}


def _to_int(value: Any) -> int | None:
    """宽容地解析整数；空值或无法识别的内容返回 None，交由调用方说明原因。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_spd(value: Any) -> str:
    """防雷模块状态统一成 正常 / 故障 / 未采集 三种展示口径。"""
    text = str(value or "").strip()
    if not text:
        return "未采集"
    if text in SPD_NORMAL:
        return "正常"
    if text in SPD_FAULT:
        return "故障"
    return text


def _parse_branches(value: Any) -> list[int]:
    """把「3,7,12」「3 7」之类的入参解析成去重排序后的支路号列表。"""
    if isinstance(value, (list, tuple, set)):
        tokens = [str(item) for item in value]
    else:
        tokens = str(value or "").replace("，", ",").replace("、", ",").replace(";", ",").split(",")
    branches = {int(token) for token in (t.strip() for t in tokens) if token.isdigit()}
    return sorted(branches)


class CombinerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        array: str | None = None,
        status: str | None = None,
        locate: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        # 跨方阵定位时放开方阵与运行状态限制，保证同一台设备不会因重复条件被捞出两遍。
        if not locate:
            if array:
                rows = [row for row in rows if array in str(row.get("所属方阵", ""))]
            if status:
                rows = [row for row in rows if row.get("status") == status]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("汇流箱编号", ""))]

        # 同一汇流箱可能在多个方阵视图里各登记一次，按 id 去重后再排序分页。
        deduped: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows:
            entry_id = int(row.get("id", 0))
            if entry_id in seen:
                continue
            seen.add(entry_id)
            deduped.append(row)

        items = [self._present(row) for row in deduped]
        items.sort(key=self._sort_key)
        total = len(items)
        start = max(page - 1, 0) * size
        return items[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        # 详情与列表走同一个出口，防雷模块状态等字段口径保持一致。
        return self._present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
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
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "登记支路异常":
            branches = _parse_branches(values.get("异常支路号"))
            if branches:
                entry["异常支路号"] = branches
                return self._present(entry), f"汇流箱已{action}，异常支路：{'、'.join(map(str, branches))}"
            existing = _parse_branches(entry.get("异常支路号"))
            if existing:
                return self._present(entry), f"汇流箱已{action}，异常支路：{'、'.join(map(str, existing))}"
            # 不指定支路号也要允许登记（老动作照旧），但提示值班人补录定位信息。
            return self._present(entry), f"汇流箱已{action}（未指定异常支路号，建议补录）"
        # 确认正常与更换设备都意味着异常已闭环，清掉历史支路标记，避免红色支路号残留。
        entry["异常支路号"] = []
        return self._present(entry), f"汇流箱已{action}"

    # ---- 以下为内部辅助 -------------------------------------------------

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表行与详情共用的序列化出口：归一化数值、电压区间与防雷状态。"""
        item = dict(row)

        raw_strings = row.get("接入组串数")
        string_count = _to_int(raw_strings)
        reason = str(row.get("组串数缺失原因") or "").strip()
        if string_count is None:
            # 没填组串数的设备不能在列表里被漏掉，要把原因写清楚。
            if not reason:
                reason = "未采集：现场尚未回填组串台账" if raw_strings in (None, "") else (
                    f"数据异常：接入组串数无法识别（原值：{raw_strings}）"
                )
        item["接入组串数"] = string_count
        item["组串数缺失原因"] = reason or None

        voltage = _to_float(row.get("直流电压"))
        item["直流电压"] = voltage
        if voltage is None:
            item["电压状态"] = "未采集"
        elif voltage > VOLTAGE_MAX:
            item["电压状态"] = "偏高"
        elif voltage < VOLTAGE_MIN:
            item["电压状态"] = "偏低"
        else:
            item["电压状态"] = "正常"

        item["异常支路号"] = _parse_branches(row.get("异常支路号"))
        item["防雷模块状态"] = _normalize_spd(row.get("防雷模块状态"))
        return item

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[int, float, float, int]:
        # 支路异常的设备置顶；其余按接入组串数、直流电压升序，缺数据的沉底；最后用 id 保证顺序稳定。
        abnormal_rank = 0 if item.get("status") == "支路异常" else 1
        string_count = item.get("接入组串数")
        voltage = item.get("直流电压")
        return (
            abnormal_rank,
            float(string_count) if isinstance(string_count, int) else float("inf"),
            float(voltage) if isinstance(voltage, (int, float)) else float("inf"),
            int(item.get("id", 0)),
        )
