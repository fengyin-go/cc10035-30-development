"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class NamespacePayload(BaseModel):
    external_namespace: str
    local_relation_type: str
    partner_code: str | None = None


class PartnerFilePayload(BaseModel):
    partner_code: str
    file_batch: str
    file_kind: str = "initial"
    conflict_policy: str = "await_partner_correction"
    declarations: list[dict[str, Any]] = Field(default_factory=list)


class EdgeRegisterPayload(BaseModel):
    edge_id: str
    source_entity: str
    target_entity: str
    relation_type: str
    source_page: str
    external_namespace: str
    external_relation_id: str
    old_edge_id: str | None = None
    origin_evidence: str | None = None
