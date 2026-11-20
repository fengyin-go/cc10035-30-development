"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 外部知识声明对接专用表：独立于 18 个业务模块表，不进运营概览的模块计数。
        self._evidence_tables: dict[str, list[dict[str, Any]]] = {
            "external_namespaces": [],   # 外部关系命名空间 ↔ 本站关系标识对照
            "partner_files": [],         # 合作方原始来件（首次件/更正件都原样留存）
            "external_claims": [],       # 外部知识声明（同一声明身份只保留一条）
            "edge_evidence": [],         # 已附到本站有向边上的外部证据
            "review_checklist": [],      # 图谱复核清单（导入结果回写）
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def evidence_rows(self, table: str) -> list[dict[str, Any]]:
        return self._evidence_tables.setdefault(table, [])

    def next_id(self, table: str) -> int:
        """给业务表或证据表生成下一个自增主键。"""
        if table in self._evidence_tables:
            rows = self._evidence_tables[table]
        else:
            rows = self.rows(table)
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
