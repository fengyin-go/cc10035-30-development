"""关系图谱领域服务：构建实体语义关系图。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


RELATION_TYPES = [
    "从属关系", "引用关系", "时序关系", "同义关系",
    "因果关系", "对比关系", "并列关系", "层级关系",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 已核验的有向边状态：只有这些边能接纳外部声明证据。
EVIDENCE_ELIGIBLE_STATUSES = ("已验证", "已入库")
# 复核清单条目的全部状态。
REVIEW_STATUSES = (
    "待核实出处",   # 历史边未记录外部命名空间，来源待核实
    "待外方更正",   # 旧号指向与已核验关系属性冲突
    "待人工裁决",   # 同页同端点匹配到多条边等歧义
    "已附证据",     # 声明已作为外部证据附到一条有效有向边
    "待匹配边",     # 本站尚无对应有向边
)


class RelationGraphService(BaseModuleService):
    MODULE = "relation_graph"
    ENTITY = "关系边"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["边ID", "源实体", "目标实体", "关系类型", "抽取页面", "原文证据", "关联强度"]
    REQUIRED_FIELDS = ["边ID", "源实体", "目标实体"]
    STATUS_ORDER = ["已抽取", "已验证", "已入库", "已过期"]
    ACTION_RULES = {"验证关系": "已验证", "确认入库": "已入库", "标记过期": "已过期"}
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """通用登记入口（建边入口二）：重定向到带证据同步的登记逻辑。"""
        return self.register_generic_edge(values)

    def find_edge_by_id(self, edge_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(self.MODULE) if row.get("边ID") == edge_id),
            None,
        )

    def find_edge_by_endpoints(
        self, source_page: str, source_entity: str, target_entity: str
    ) -> list[dict[str, Any]]:
        """按来源页 + 有向端点定位本站有向边（方向敏感：A→B 不匹配 B→A）。

        已过期（被换号取代）的边不再是有效有向边，不参与原边核对。
        """
        matches = []
        for row in store.rows(self.MODULE):
            if row.get("status") == "已过期":
                continue
            if (
                row.get("抽取页面") == source_page
                and row.get("源实体") == source_entity
                and row.get("目标实体") == target_entity
            ):
                matches.append(row)
        return matches

    def register_renumbered_edge(
        self,
        *,
        edge_id: str,
        source_entity: str,
        target_entity: str,
        relation_type: str,
        source_page: str,
        external_namespace: str,
        external_relation_id: str,
        old_edge_id: str | None = None,
        origin_evidence: str = "",
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """建边入口一：图谱登记同页有向边换号证据。

        新边带外部命名空间，登记为「已验证」后立即触发知识链接对等待中的外部声明
        重新核对，并把已核定证据同步到该边。
        """
        required = {
            "边ID": edge_id,
            "源实体": source_entity,
            "目标实体": target_entity,
            "关系类型": relation_type,
            "抽取页面": source_page,
            "外部命名空间": external_namespace,
            "外部关系标识": external_relation_id,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            return None, missing
        if self.find_edge_by_id(edge_id) is not None:
            return None, [f"边ID「{edge_id}」已存在，不能重复登记"]

        entry = {"id": store.next_id(self.MODULE)}
        entry.update({
            "边ID": edge_id,
            "源实体": source_entity,
            "目标实体": target_entity,
            "关系类型": relation_type,
            "抽取页面": source_page,
            "原文证据": origin_evidence or "换号登记",
            "关联强度": "0.90",
            "外部命名空间": external_namespace,
            "外部关系标识": external_relation_id,
            "旧边编号": old_edge_id or "",
        })
        entry["status"] = "已验证"
        entry["pending"] = entry["status"] != self.STATUS_ORDER[-1]
        entry["abnormal"] = False
        store.rows(self.MODULE).append(entry)

        # 换号成立：旧边编号指向的本站边标记过期，原边核对只认新的有效有向边。
        superseded = None
        if old_edge_id:
            superseded = self.find_edge_by_id(old_edge_id)
            if superseded is not None and superseded.get("id") != entry["id"]:
                superseded["status"] = "已过期"
                superseded["pending"] = False
                superseded["换号后继"] = edge_id
            entry["原文证据"] = (
                origin_evidence
                or f"换号登记：旧边编号 {old_edge_id} 已过期，由 {edge_id} 接替"
            )

        # 建边入口同步取得已核定的外部证据：委托知识链接按来源页+有向端点重核。
        from app.services.knowledge_link import KnowledgeLinkService
        sync_result = KnowledgeLinkService().recheck_claims_for_edge(entry)
        sync_result["superseded_edge_id"] = superseded.get("边ID") if superseded else ""
        return entry, sync_result.get("attached", [])

    def register_generic_edge(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """建边入口二：通用资源登记入口。

        与换号入口走同一套证据同步逻辑；未带外部命名空间时按历史边处理，
        对应来件保持「待核实出处」，不会自动附证据。
        """
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        if self.find_edge_by_id(str(values.get("边ID"))) is not None:
            return None, [f"边ID「{values.get('边ID')}」已存在，不能重复登记"]
        entry = {"id": store.next_id(self.MODULE)}
        entry.update({field: values.get(field) for field in self.LIST_FIELDS})
        entry["外部命名空间"] = values.get("外部命名空间", "") or ""
        entry["外部关系标识"] = values.get("外部关系标识", "") or ""
        entry["旧边编号"] = values.get("旧边编号", "") or ""
        entry["status"] = "已验证" if entry["外部命名空间"] else "已抽取"
        entry["pending"] = entry["status"] != self.STATUS_ORDER[-1]
        entry["abnormal"] = False
        store.rows(self.MODULE).append(entry)

        attached: list[str] = []
        if entry["外部命名空间"]:
            from app.services.knowledge_link import KnowledgeLinkService
            attached = KnowledgeLinkService().recheck_claims_for_edge(entry).get("attached", [])
        entry["同步证据"] = attached
        return entry, []

    def edge_evidence_list(self, edge_id: str | None = None) -> list[dict[str, Any]]:
        """边证据清单：每条已确认证据唯一对应本站一条有效有向边。"""
        rows = store.evidence_rows("edge_evidence")
        if edge_id:
            rows = [row for row in rows if row.get("edge_id") == edge_id]
        return rows

    def review_checklist(self, status: str | None = None) -> list[dict[str, Any]]:
        """图谱复核清单：导入结果回写，供图谱侧逐条处理。"""
        rows = store.evidence_rows("review_checklist")
        if status:
            rows = [row for row in rows if row.get("review_status") == status]
        return rows

    def verify_historical_provenance(self, review_id: int) -> tuple[dict[str, Any] | None, str]:
        """核实历史边出处：核实通过后对应来件才生效并附证据。"""
        item = next(
            (row for row in store.evidence_rows("review_checklist") if int(row.get("id", 0)) == review_id),
            None,
        )
        if item is None:
            return None, f"复核条目 {review_id} 不存在"
        if item.get("review_status") != "待核实出处":
            return None, f"复核条目当前状态为「{item.get('review_status')}」，无需核实出处"

        from app.services.knowledge_link import KnowledgeLinkService
        claim = KnowledgeLinkService().get_claim(item["claim_id"])
        if claim is None:
            return None, "对应外部知识声明不存在"
        edge = self.find_edge_by_id(item.get("edge_id", ""))
        if edge is None:
            return None, f"本站边「{item.get('edge_id')}」已失效，无法附证据"
        if edge.get("status") not in EVIDENCE_ELIGIBLE_STATUSES:
            return None, f"边「{edge.get('边ID')}」状态为{edge.get('status')}，尚不是有效有向边"

        # 出处核实后，给历史边补记命名空间并接纳证据。
        edge["外部命名空间"] = claim["external_namespace"]
        edge["外部关系标识"] = claim["external_relation_id"]
        attached = KnowledgeLinkService().attach_claim_to_edge(claim, edge, reason="出处核实通过后补附")
        item["review_status"] = "已附证据"
        item["resolved_at"] = utc_now()
        item["resolution"] = "出处核实通过，证据已生效"
        return item, attached.get("evidence_id", "")

    def build_relations(self, entity_extract_records: list[dict[str, Any]]) -> dict[str, Any]:
        """基于实体抽取记录构建关系图谱。消费 entity_extract 输出。"""
        if len(entity_extract_records) < 2:
            return {"ok": True, "relation_count": 0, "relations": [], "reason": "实体数量不足"}

        relations = []
        for i in range(len(entity_extract_records)):
            for j in range(i + 1, min(i + 4, len(entity_extract_records))):
                src = entity_extract_records[i]
                tgt = entity_extract_records[j]
                if src.get("页面来源") != tgt.get("页面来源"):
                    continue
                rel_type_idx = (i * 7 + j * 13) % len(RELATION_TYPES)
                edge_id = hashlib.md5(
                    f"{src.get('实体ID')}|{tgt.get('实体ID')}|{RELATION_TYPES[rel_type_idx]}".encode()
                ).hexdigest()[:10]
                strength = round(0.85 - (abs(i - j) * 0.08), 2)
                relations.append({
                    "边ID": edge_id,
                    "源实体": src.get("实体名称", src.get("实体ID", "")),
                    "目标实体": tgt.get("实体名称", tgt.get("实体ID", "")),
                    "关系类型": RELATION_TYPES[rel_type_idx],
                    "抽取页面": src.get("页面来源"),
                    "原文证据": f"从{src.get('页面来源')}中抽取的共现关系",
                    "关联强度": str(strength),
                })

        return {
            "ok": True,
            "entity_count": len(entity_extract_records),
            "relation_count": len(relations),
            "relations": relations,
            "relation_types_used": list(set(r["关系类型"] for r in relations)),
        }

    def feed_knowledge_link(self, relation_ids: list[str]) -> dict[str, Any]:
        """将已验证的关系提供给知识链接模块。"""
        relations = []
        for rid in relation_ids:
            row = self.find_edge_by_id(rid)
            if row and row.get("status") == "已验证":
                relations.append({
                    "edge_id": rid,
                    "source_entity": row.get("源实体"),
                    "target_entity": row.get("目标实体"),
                    "relation_type": row.get("关系类型"),
                    "evidence_page": row.get("抽取页面"),
                    "external_namespace": row.get("外部命名空间", ""),
                    "external_relation_id": row.get("外部关系标识", ""),
                })
        return {
            "ok": True,
            "requested_ids": len(relation_ids),
            "found_relations": len(relations),
            "relations": relations,
        }

    def compute_graph_stats(self) -> dict[str, Any]:
        """图谱统计。"""
        rows = store.rows(self.MODULE)
        entities: set[str] = set()
        rel_type_dist: dict[str, int] = {}
        for row in rows:
            entities.add(str(row.get("源实体", "")))
            entities.add(str(row.get("目标实体", "")))
            rtype = row.get("关系类型", "未知")
            rel_type_dist[rtype] = rel_type_dist.get(rtype, 0) + 1
        return {
            "total_relations": len(rows),
            "unique_entities": len(entities) - (1 if "" in entities else 0),
            "relation_type_distribution": rel_type_dist,
            "validated": sum(1 for r in rows if r.get("status") == "已验证"),
            "ingested": sum(1 for r in rows if r.get("status") == "已入库"),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["graph_stats"] = self.compute_graph_stats()
        base["external_evidence"] = {
            "evidence_count": len(store.evidence_rows("edge_evidence")),
            "pending_review": sum(
                1 for row in store.evidence_rows("review_checklist")
                if row.get("review_status") != "已附证据"
            ),
            "attached_edges": len({
                row.get("edge_id") for row in store.evidence_rows("edge_evidence")
            }),
        }
        return base