"""外部知识声明对接路由。

承载合作图谱文件导入、命名空间对照、图谱复核清单和边证据查询。
本路由全部为固定路径，必须在通配的 resource 路由之前注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import EdgeRegisterPayload, NamespacePayload, PartnerFilePayload
from app.services.knowledge_link import KnowledgeLinkService
from app.services.relation_graph import RelationGraphService
from app.store import store

router = APIRouter(prefix="/api/knowledge-evidence", tags=["外部知识声明对接"])

link_service = KnowledgeLinkService()
graph_service = RelationGraphService()


@router.post("/namespaces")
def register_namespace(payload: NamespacePayload) -> dict[str, Any]:
    """登记外部关系命名空间与本站关系标识的对照。"""
    entry, missing = link_service.register_namespace(payload.model_dump())
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少必填字段：{'、'.join(missing)}")
    return {"ok": True, "message": "命名空间对照已登记", "entry": entry}


@router.get("/namespaces")
def list_namespaces() -> dict[str, Any]:
    return {"ok": True, "items": store.evidence_rows("external_namespaces")}


@router.post("/partner-imports")
def import_partner_file(payload: PartnerFilePayload) -> dict[str, Any]:
    """导入合作方图谱文件：返回导入回执，内含每条声明实际配对的数据。"""
    result = link_service.import_partner_file(payload.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result["message"])
    return result


@router.get("/partner-imports")
def list_partner_imports() -> dict[str, Any]:
    """来件登记列表：首次件与更正件都可查，原始来件按 id 单独取。"""
    return {"ok": True, "items": link_service.list_partner_files()}


@router.get("/partner-imports/{file_id}")
def get_partner_import(file_id: int) -> dict[str, Any]:
    row = link_service.get_partner_file(file_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"来件 {file_id} 不存在")
    return {"ok": True, "item": row}


@router.get("/claims")
def list_claims(status: str | None = Query(default=None)) -> dict[str, Any]:
    """外部知识声明数据包列表，可按声明状态过滤。"""
    return {"ok": True, "items": link_service.list_claims(status)}


@router.get("/edge-evidence")
def edge_evidence(edge_id: str | None = Query(default=None)) -> dict[str, Any]:
    """边证据清单：每条确认证据唯一对应本站一条有效有向边。"""
    items = graph_service.edge_evidence_list(edge_id)
    return {"ok": True, "total": len(items), "items": items}


@router.get("/review-checklist")
def review_checklist(status: str | None = Query(default=None)) -> dict[str, Any]:
    """图谱复核清单：导入结果回写，图谱侧按状态逐条处理。"""
    items = graph_service.review_checklist(status)
    return {"ok": True, "total": len(items), "items": items}


@router.post("/review-checklist/{review_id}/verify-provenance")
def verify_provenance(review_id: int) -> dict[str, Any]:
    """核实历史边出处：核实通过后来件生效，证据附到对应有向边。"""
    item, message = graph_service.verify_historical_provenance(review_id)
    if item is None:
        raise HTTPException(status_code=422, detail=message)
    return {"ok": True, "message": message, "entry": item}


@router.post("/edges/register-renumber")
def register_renumbered_edge(payload: EdgeRegisterPayload) -> dict[str, Any]:
    """建边入口一：图谱登记同页有向边换号证据，同步取得已核定外部证据。"""
    entry, attached = graph_service.register_renumbered_edge(**payload.model_dump())
    if entry is None:
        raise HTTPException(status_code=422, detail=f"缺少必填字段：{'、'.join(attached)}")
    return {
        "ok": True,
        "message": f"换号有向边 {entry['边ID']} 已登记并复核外部声明",
        "entry": entry,
        "synced_claim_ids": attached,
    }
