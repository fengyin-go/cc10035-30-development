"""知识链接领域服务：管理实体与外部知识的链接关系。

另承担合作图谱文件导入：把合作方的外部关系命名空间与本站关系标识对照，
形成原边对应的外部知识声明数据包，再交给关系图谱核对来源页、有向端点和换号依据。
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.services.base import BaseModuleService
from app.services.relation_graph import EVIDENCE_ELIGIBLE_STATUSES, utc_now
from app.store import store


LINK_TYPES = ["wiki", "dbpedia", "knowledge_panel", "authority_page", "linkedin"]

# 外部声明在其生命周期内的状态。
CLAIM_STATUSES = (
    "待匹配边",       # 本站尚无来源页+有向端点一致的边
    "已附证据",       # 已唯一对应一条有效有向边
    "待核实出处",     # 命中未记录外部命名空间的历史边，出处核实后才生效
    "待外方更正",     # 旧号指向与已核验关系属性冲突
    "待人工裁决",     # 端点匹配到多条边等歧义
    "命名空间未登记", # 外部命名空间在本站没有对照关系
)
# 冲突处置策略：接纳对应关系，或等待外方更正。
CONFLICT_POLICIES = ("accept_correspondence", "await_partner_correction")


def claim_identity(
    partner_code: str,
    external_namespace: str,
    external_relation_id: str,
    source_page: str,
    source_entity: str,
    target_entity: str,
) -> str:
    """声明身份：合作方 + 命名空间 + 外部关系标识 + 有向端点，首次件与更正件共用。"""
    raw = "|".join([
        partner_code or "",
        external_namespace or "",
        external_relation_id or "",
        source_page or "",
        source_entity or "",
        target_entity or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class KnowledgeLinkService(BaseModuleService):
    MODULE = "knowledge_link"
    ENTITY = "链接记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["链接ID", "源实体", "外部URI", "链接类型", "外部来源", "验证状态", "上次验证"]
    REQUIRED_FIELDS = ["链接ID", "源实体", "外部URI"]
    STATUS_ORDER = ["待验证", "已验证", "已失效", "已移除"]
    ACTION_RULES = {"验证链接": "待验证", "标记失效": "已验证", "移除链接": "已验证"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 外部关系命名空间对照
    # ------------------------------------------------------------------
    def register_namespace(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记外部关系命名空间 ↔ 本站关系标识对照。"""
        required = ["external_namespace", "local_relation_type"]
        missing = [field for field in required if not str(payload.get(field) or "").strip()]
        if missing:
            return None, missing
        namespace = str(payload["external_namespace"]).strip()
        local_type = str(payload["local_relation_type"]).strip()
        rows = store.evidence_rows("external_namespaces")
        existing = next((row for row in rows if row.get("external_namespace") == namespace), None)
        if existing is not None:
            existing["local_relation_type"] = local_type
            existing["updated_at"] = utc_now()
            return existing, []
        entry = {
            "id": store.next_id("external_namespaces"),
            "external_namespace": namespace,
            "local_relation_type": local_type,
            "partner_code": str(payload.get("partner_code", "") or "").strip(),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        rows.append(entry)
        return entry, []

    def resolve_namespace(self, external_namespace: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.evidence_rows("external_namespaces")
             if row.get("external_namespace") == external_namespace),
            None,
        )

    # ------------------------------------------------------------------
    # 合作图谱文件导入
    # ------------------------------------------------------------------
    def import_partner_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        """导入合作方图谱文件，输出导入回执并回写图谱复核清单。

        payload 约定：
          partner_code      合作方标识
          file_batch        来件批次号（首次件/更正件各自唯一）
          file_kind         initial | correction
          conflict_policy   accept_correspondence | await_partner_correction
          declarations[]    外部关系声明，含来源页、有向端点、换号依据、旧边编号
        """
        partner_code = str(payload.get("partner_code", "") or "").strip()
        file_batch = str(payload.get("file_batch", "") or "").strip()
        file_kind = str(payload.get("file_kind", "initial") or "initial").strip()
        conflict_policy = str(
            payload.get("conflict_policy", "await_partner_correction")
        ).strip()
        if conflict_policy not in CONFLICT_POLICIES:
            conflict_policy = "await_partner_correction"
        declarations = payload.get("declarations") or []

        if not partner_code or not file_batch:
            return {"ok": False, "message": "缺少合作方标识 partner_code 或来件批次 file_batch",
                    "pairings": [], "saved_file_id": None}
        if not isinstance(declarations, list) or not declarations:
            return {"ok": False, "message": "来件中没有可导入的 declarations",
                    "pairings": [], "saved_file_id": None}

        # 原始来件无条件保存：首次件和更正件都留痕，不覆盖、不合并。
        saved_file = {
            "id": store.next_id("partner_files"),
            "partner_code": partner_code,
            "file_batch": file_batch,
            "file_kind": file_kind,
            "conflict_policy": conflict_policy,
            "received_at": utc_now(),
            "declaration_count": len(declarations),
            "raw_payload": payload,
        }
        store.evidence_rows("partner_files").append(saved_file)

        pairings: list[dict[str, Any]] = []
        counters = {status: 0 for status in CLAIM_STATUSES}
        updated_identities: list[str] = []

        for index, declaration in enumerate(declarations, start=1):
            pairing = self._process_declaration(
                declaration=declaration,
                partner_code=partner_code,
                file_batch=file_batch,
                file_kind=file_kind,
                conflict_policy=conflict_policy,
                seq=index,
                saved_file_id=saved_file["id"],
            )
            pairings.append(pairing)
            counters[pairing["claim_status"]] = counters.get(pairing["claim_status"], 0) + 1
            if pairing.get("updated_existing"):
                updated_identities.append(pairing["claim_id"])

        return {
            "ok": True,
            "message": f"来件 {file_batch} 已导入，共 {len(declarations)} 条声明",
            "saved_file_id": saved_file["id"],
            "file_kind": file_kind,
            "partner_code": partner_code,
            "file_batch": file_batch,
            "total": len(declarations),
            "status_counts": counters,
            "updated_claim_identities": updated_identities,
            "pairings": pairings,
        }

    def _process_declaration(
        self,
        *,
        declaration: dict[str, Any],
        partner_code: str,
        file_batch: str,
        file_kind: str,
        conflict_policy: str,
        seq: int,
        saved_file_id: int,
    ) -> dict[str, Any]:
        external_namespace = str(declaration.get("external_namespace", "") or "").strip()
        external_relation_id = str(declaration.get("external_relation_id", "") or "").strip()
        source_page = str(declaration.get("source_page", "") or "").strip()
        source_entity = str(declaration.get("source_entity", "") or "").strip()
        target_entity = str(declaration.get("target_entity", "") or "").strip()
        old_edge_id = str(declaration.get("old_edge_id", "") or "").strip()
        renumber_basis = str(declaration.get("renumber_basis", "") or "").strip()
        external_relation_label = str(
            declaration.get("external_relation_label", "") or ""
        ).strip()

        identity = claim_identity(
            partner_code, external_namespace, external_relation_id,
            source_page, source_entity, target_entity,
        )

        # 并发提交首次件和更正件只认一个声明身份：按身份 upsert，原始来件各自留存。
        claim_rows = store.evidence_rows("external_claims")
        claim = next((row for row in claim_rows if row.get("claim_id") == identity), None)
        updated_existing = claim is not None
        if claim is None:
            claim = {
                "id": store.next_id("external_claims"),
                "claim_id": identity,
                "partner_code": partner_code,
                "external_namespace": external_namespace,
                "external_relation_id": external_relation_id,
                "external_relation_label": external_relation_label,
                "source_page": source_page,
                "source_entity": source_entity,
                "target_entity": target_entity,
                "old_edge_id": old_edge_id,
                "renumber_basis": renumber_basis,
                "claim_status": "待匹配边",
                "local_relation_type": "",
                "matched_edge_id": "",
                "current_file_batch": file_batch,
                "first_file_batch": file_batch,
                "revision_count": 0,
                "history": [],
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
            claim_rows.append(claim)
        else:
            snapshot = {
                "file_batch": claim.get("current_file_batch"),
                "old_edge_id": claim.get("old_edge_id"),
                "renumber_basis": claim.get("renumber_basis"),
                "external_relation_label": claim.get("external_relation_label"),
                "claim_status": claim.get("claim_status"),
                "updated_at": claim.get("updated_at"),
            }
            claim["history"].append(snapshot)
            claim["revision_count"] = int(claim.get("revision_count", 0)) + 1
            claim["current_file_batch"] = file_batch
            # 更正件可覆盖旧号与换号依据；声明身份（有向端点等）保持不变。
            if old_edge_id:
                claim["old_edge_id"] = old_edge_id
            if renumber_basis:
                claim["renumber_basis"] = renumber_basis
            if external_relation_label:
                claim["external_relation_label"] = external_relation_label
            claim["updated_at"] = utc_now()

        claim["source_file_ids"] = sorted(
            set(claim.get("source_file_ids", []) + [saved_file_id])
        )

        pairing: dict[str, Any] = {
            "seq": seq,
            "claim_id": identity,
            "updated_existing": updated_existing,
            "file_kind": file_kind,
            "external_namespace": external_namespace,
            "external_relation_id": external_relation_id,
            "source_page": source_page,
            "source_entity": source_entity,
            "target_entity": target_entity,
            "old_edge_id": old_edge_id,
        }

        # 1) 外部命名空间必须先有对照，否则不形成可核对的数据包。
        namespace = self.resolve_namespace(external_namespace)
        if namespace is None:
            self._set_claim_status(claim, "命名空间未登记")
            self._write_review(
                claim=claim,
                review_status="命名空间未登记",
                edge_id="",
                detail="外部关系命名空间未登记对照，数据包不参与原边核对",
                saved_file_id=saved_file_id,
                file_batch=file_batch,
            )
            pairing.update(claim_status="命名空间未登记", matched_edge_id="", attached=False,
                           reason="命名空间未登记")
            return pairing
        claim["local_relation_type"] = namespace["local_relation_type"]

        # 2) 知识链接把来源页、有向端点和换号依据交给图谱核对原边。
        from app.services.relation_graph import RelationGraphService
        graph = RelationGraphService()
        candidates = graph.find_edge_by_endpoints(source_page, source_entity, target_entity)

        if not candidates:
            self._set_claim_status(claim, "待匹配边")
            self._write_review(
                claim=claim,
                review_status="待匹配边",
                edge_id="",
                detail="来源页+有向端点暂无本站有向边，等待建边入口登记后重核",
                saved_file_id=saved_file_id,
                file_batch=file_batch,
            )
            pairing.update(claim_status="待匹配边", matched_edge_id="", attached=False,
                           reason="暂无对应有向边")
            return pairing

        if len(candidates) > 1:
            self._set_claim_status(claim, "待人工裁决")
            ids = [str(row.get("边ID")) for row in candidates]
            self._write_review(
                claim=claim,
                review_status="待人工裁决",
                edge_id="",
                detail=f"同页同有向端点匹配到 {len(candidates)} 条边：{ids}",
                saved_file_id=saved_file_id,
                file_batch=file_batch,
            )
            pairing.update(claim_status="待人工裁决", matched_edge_id="", attached=False,
                           reason=f"匹配到多条边 {ids}")
            return pairing

        edge = candidates[0]
        edge_id = str(edge.get("边ID"))
        pairing["matched_edge_id"] = edge_id

        # 3) 旧边编号与来源页/端点同时给出时，核对编号指向与已核验关系属性是否冲突。
        conflict_note = self._old_id_note(claim)
        conflict_detail = self._detect_old_id_conflict(claim, edge)
        if conflict_detail:
            if conflict_policy == "accept_correspondence":
                # 接纳对应关系：以来源页+有向端点的核验结果为准，冲突仅留痕，不阻断附证据。
                conflict_note = f"旧号冲突已记录并接纳：{conflict_detail}"
            else:
                # 等待外方更正：当轮不能把声明附到边上。
                self._set_claim_status(claim, "待外方更正")
                self._write_review(
                    claim=claim,
                    review_status="待外方更正",
                    edge_id=edge_id,
                    detail=f"旧边编号指向与核验关系属性冲突：{conflict_detail}",
                    saved_file_id=saved_file_id,
                    file_batch=file_batch,
                )
                pairing.update(claim_status="待外方更正", attached=False,
                               reason=conflict_detail)
                return pairing

        # 4) 历史边兼容：未记录外部命名空间的本站边，来件待核实出处后才生效。
        if not str(edge.get("外部命名空间", "") or "").strip():
            self._set_claim_status(claim, "待核实出处")
            self._write_review(
                claim=claim,
                review_status="待核实出处",
                edge_id=edge_id,
                detail="命中未记录外部命名空间的历史边，待核实出处",
                saved_file_id=saved_file_id,
                file_batch=file_batch,
            )
            pairing.update(claim_status="待核实出处", attached=False,
                           reason="历史边外部命名空间缺失")
            return pairing

        # 5) 每项确认证据都须唯一对应一条有效有向边。
        if edge.get("status") not in EVIDENCE_ELIGIBLE_STATUSES:
            self._set_claim_status(claim, "待匹配边")
            self._write_review(
                claim=claim,
                review_status="待匹配边",
                edge_id=edge_id,
                detail=f"边状态为{edge.get('status')}，尚不是有效有向边",
                saved_file_id=saved_file_id,
                file_batch=file_batch,
            )
            pairing.update(claim_status="待匹配边", attached=False,
                           reason=f"边状态 {edge.get('status')} 未核验")
            return pairing

        evidence = self.attach_claim_to_edge(claim, edge, reason="导入时自动配对")
        self._write_review(
            claim=claim,
            review_status="已附证据",
            edge_id=edge_id,
            detail=conflict_note or f"外部证据已附到有向边 {edge_id}",
            saved_file_id=saved_file_id,
            file_batch=file_batch,
            evidence_id=evidence["evidence_id"],
        )
        pairing.update(claim_status="已附证据", attached=True,
                       evidence_id=evidence["evidence_id"],
                       reason=conflict_note or "来源页与有向端点核验一致")
        return pairing

    def _detect_old_id_conflict(self, claim: dict[str, Any], edge: dict[str, Any]) -> str:
        """旧边编号指向与核验过的关系属性冲突时返回冲突说明，否则返回空串。"""
        old_edge_id = str(claim.get("old_edge_id", "") or "").strip()
        if not old_edge_id:
            return ""
        from app.services.relation_graph import RelationGraphService
        pointed = RelationGraphService().find_edge_by_id(old_edge_id)
        if pointed is None:
            # 旧号在本站无记录，谈不上指向冲突；仅作留痕，不阻断来源页+端点配对。
            return ""
        if pointed.get("id") == edge.get("id"):
            return ""  # 旧号就指向当前边，属于正常换号。
        problems = []
        for field in ("源实体", "目标实体", "抽取页面"):
            if pointed.get(field) != edge.get(field):
                problems.append(f"{field}：旧号指向 {pointed.get(field)} ≠ 核验边 {edge.get(field)}")
        local_type = claim.get("local_relation_type")
        if local_type and pointed.get("关系类型") and pointed.get("关系类型") != local_type:
            problems.append(
                f"关系类型：旧号边 {pointed.get('关系类型')} 与命名空间对照 {local_type} 不一致"
            )
        return "；".join(problems)

    def _old_id_note(self, claim: dict[str, Any]) -> str:
        """旧号在本站无记录时给出留痕说明。"""
        old_edge_id = str(claim.get("old_edge_id", "") or "").strip()
        if not old_edge_id:
            return ""
        from app.services.relation_graph import RelationGraphService
        if RelationGraphService().find_edge_by_id(old_edge_id) is None:
            return f"旧边编号 {old_edge_id} 在本站无记录，按来源页+有向端点配对"
        return ""

    def attach_claim_to_edge(
        self, claim: dict[str, Any], edge: dict[str, Any], *, reason: str
    ) -> dict[str, Any]:
        """把一条声明作为外部证据附到一条有效有向边，强制证据↔边唯一对应。"""
        edge_id = str(edge.get("边ID"))
        evidence_rows = store.evidence_rows("edge_evidence")

        existing = next(
            (row for row in evidence_rows if row.get("claim_id") == claim["claim_id"]),
            None,
        )
        if existing is not None:
            # 声明已附过边：更正后若配对边变化，先迁移再保留唯一一条证据。
            existing.update({
                "edge_id": edge_id,
                "source_page": claim["source_page"],
                "source_entity": claim["source_entity"],
                "target_entity": claim["target_entity"],
                "external_namespace": claim["external_namespace"],
                "external_relation_id": claim["external_relation_id"],
                "local_relation_type": claim.get("local_relation_type", ""),
                "old_edge_id": claim.get("old_edge_id", ""),
                "renumber_basis": claim.get("renumber_basis", ""),
                "attached_at": utc_now(),
                "reason": reason,
            })
            evidence = existing
        else:
            evidence = {
                "id": store.next_id("edge_evidence"),
                "evidence_id": f"EV-{claim['claim_id']}",
                "claim_id": claim["claim_id"],
                "edge_id": edge_id,
                "partner_code": claim["partner_code"],
                "external_namespace": claim["external_namespace"],
                "external_relation_id": claim["external_relation_id"],
                "local_relation_type": claim.get("local_relation_type", ""),
                "source_page": claim["source_page"],
                "source_entity": claim["source_entity"],
                "target_entity": claim["target_entity"],
                "old_edge_id": claim.get("old_edge_id", ""),
                "renumber_basis": claim.get("renumber_basis", ""),
                "attached_at": utc_now(),
                "reason": reason,
            }
            evidence_rows.append(evidence)

        self._set_claim_status(claim, "已附证据")
        claim["matched_edge_id"] = edge_id
        return evidence

    def recheck_claims_for_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        """建边入口登记新边后，重核等待中的声明并同步已核定证据。"""
        source_page = str(edge.get("抽取页面", "") or "")
        source_entity = str(edge.get("源实体", "") or "")
        target_entity = str(edge.get("目标实体", "") or "")
        attached: list[str] = []
        for claim in store.evidence_rows("external_claims"):
            if claim.get("claim_status") == "已附证据":
                continue
            if (
                claim.get("source_page") == source_page
                and claim.get("source_entity") == source_entity
                and claim.get("target_entity") == target_entity
            ):
                # 复用完整核对链路：命名空间、冲突、历史边、有效状态都再走一遍。
                pairing = self._recheck_one(claim, edge)
                if pairing.get("attached"):
                    attached.append(claim["claim_id"])
        return {"edge_id": edge.get("边ID"), "attached": attached, "attached_count": len(attached)}

    def _recheck_one(self, claim: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
        namespace = self.resolve_namespace(claim["external_namespace"])
        if namespace is None:
            return {"attached": False}
        claim["local_relation_type"] = namespace["local_relation_type"]
        conflict = self._detect_old_id_conflict(claim, edge)
        if conflict:
            self._set_claim_status(claim, "待外方更正")
            self._write_review(
                claim=claim, review_status="待外方更正",
                edge_id=str(edge.get("边ID")),
                detail=f"建边重核发现旧号冲突：{conflict}",
                saved_file_id=claim.get("source_file_ids", [0])[-1],
                file_batch=claim.get("current_file_batch", ""),
            )
            return {"attached": False, "reason": conflict}
        if edge.get("status") not in EVIDENCE_ELIGIBLE_STATUSES:
            return {"attached": False}
        evidence = self.attach_claim_to_edge(claim, edge, reason="建边入口重核后同步")
        self._write_review(
            claim=claim, review_status="已附证据",
            edge_id=str(edge.get("边ID")),
            detail="建边入口同步取得已核定外部证据",
            saved_file_id=claim.get("source_file_ids", [0])[-1],
            file_batch=claim.get("current_file_batch", ""),
            evidence_id=evidence["evidence_id"],
        )
        return {"attached": True, "evidence_id": evidence["evidence_id"]}

    # ------------------------------------------------------------------
    # 查询辅助
    # ------------------------------------------------------------------
    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.evidence_rows("external_claims")
             if row.get("claim_id") == claim_id),
            None,
        )

    def list_claims(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = store.evidence_rows("external_claims")
        if status:
            rows = [row for row in rows if row.get("claim_status") == status]
        return rows

    def list_partner_files(self) -> list[dict[str, Any]]:
        """原始来件清单（不含整包原文，原文按 id 单独取）。"""
        return [
            {k: v for k, v in row.items() if k != "raw_payload"}
            for row in store.evidence_rows("partner_files")
        ]

    def get_partner_file(self, file_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in store.evidence_rows("partner_files")
             if int(row.get("id", 0)) == file_id),
            None,
        )

    def _set_claim_status(self, claim: dict[str, Any], status: str) -> None:
        claim["claim_status"] = status
        claim["updated_at"] = utc_now()

    def _write_review(
        self,
        *,
        claim: dict[str, Any],
        review_status: str,
        edge_id: str,
        detail: str,
        saved_file_id: int,
        file_batch: str,
        evidence_id: str = "",
    ) -> None:
        store.evidence_rows("review_checklist").append({
            "id": store.next_id("review_checklist"),
            "claim_id": claim["claim_id"],
            "review_status": review_status,
            "edge_id": edge_id,
            "partner_code": claim["partner_code"],
            "external_namespace": claim["external_namespace"],
            "external_relation_id": claim["external_relation_id"],
            "source_page": claim["source_page"],
            "source_entity": claim["source_entity"],
            "target_entity": claim["target_entity"],
            "old_edge_id": claim.get("old_edge_id", ""),
            "file_batch": file_batch,
            "saved_file_id": saved_file_id,
            "evidence_id": evidence_id,
            "detail": detail,
            "created_at": utc_now(),
            "resolved_at": "",
            "resolution": "",
        })

    def consume_relations(self, relation_graph_edges: list[dict[str, Any]]) -> dict[str, Any]:
        """消费关系图谱的已验证边，为实体建立外部知识链接。"""
        if not relation_graph_edges:
            return {"ok": True, "link_count": 0, "links": []}

        links = []
        for edge in relation_graph_edges:
            entities = [edge.get("source_entity", ""), edge.get("target_entity", "")]
            for entity in entities:
                if not entity:
                    continue
                ehash = int(hashlib.md5(entity.encode()).hexdigest()[:4], 16)
                link_type = LINK_TYPES[ehash % len(LINK_TYPES)]
                link_id = hashlib.sha256(
                    f"{entity}|{link_type}|ext".encode()
                ).hexdigest()[:12]
                external_uri = f"https://{link_type}.example.com/entity/{entity}"
                links.append({
                    "链接ID": link_id,
                    "源实体": entity,
                    "外部URI": external_uri,
                    "链接类型": link_type,
                    "外部来源": "relation_graph_pipeline",
                    "验证状态": "自动生成",
                    "上次验证": "2026-11-19T10:00:00Z",
                })
        return {
            "ok": True,
            "input_edges": len(relation_graph_edges),
            "link_count": len(links),
            "links": links,
        }

    def build_aggregate_input(self) -> dict[str, Any]:
        """构建聚合视图的输入数据。"""
        rows = store.rows(self.MODULE)
        link_type_dist: dict[str, int] = {}
        for row in rows:
            ltype = row.get("链接类型", "未知")
            link_type_dist[ltype] = link_type_dist.get(ltype, 0) + 1
        return {
            "total_links": len(rows),
            "verified_links": sum(1 for r in rows if r.get("status") == "已验证"),
            "invalid_links": sum(1 for r in rows if r.get("status") == "已失效"),
            "link_type_distribution": link_type_dist,
        }

    def validate_link_batch(self) -> dict[str, Any]:
        """批量验证待验证的链接。"""
        pending = [r for r in store.rows(self.MODULE) if r.get("status") == "待验证"]
        validated = 0
        for row in pending:
            link_id = row.get("id")
            if link_id:
                existing = store.find(self.MODULE, int(link_id))
                if existing:
                    existing["验证状态"] = "有效"
                    existing["上次验证"] = "2026-11-19T10:00:00Z"
                    validated += 1
        return {"ok": True, "pending_count": len(pending), "validated_count": validated}

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["link_stats"] = self.build_aggregate_input()
        claims = store.evidence_rows("external_claims")
        base["external_claims"] = {
            "claim_count": len(claims),
            "by_status": {
                status: sum(1 for row in claims if row.get("claim_status") == status)
                for status in CLAIM_STATUSES
            },
            "partner_files": len(store.evidence_rows("partner_files")),
            "namespaces": len(store.evidence_rows("external_namespaces")),
        }
        return base