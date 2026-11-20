"""服务层补充校验：接纳对应关系策略、通用建边入口、多匹配裁决、证据迁移。

以 python -I 运行，直接操作内存仓库，不依赖 HTTP 服务。
"""
import sys

sys.path.insert(0, "/workspace/backend")

from app.services.knowledge_link import KnowledgeLinkService
from app.services.relation_graph import RelationGraphService
from app.store import store


def reset() -> None:
    for table in store._evidence_tables.values():
        table.clear()
    store.rows("relation_graph").clear()


def main() -> None:
    reset()
    link = KnowledgeLinkService()
    graph = RelationGraphService()

    link.register_namespace({
        "external_namespace": "px-rel",
        "local_relation_type": "从属关系",
        "partner_code": "PARTNER-Y",
    })

    # 本站边：核验边 + 旧号实际指向的另一条边（制造冲突）。
    edge, missing = graph.register_generic_edge({
        "边ID": "E-VERIFIED", "源实体": "A", "目标实体": "B",
        "关系类型": "从属关系", "抽取页面": "page-1",
        "原文证据": "", "关联强度": "0.9",
        "外部命名空间": "px-rel", "外部关系标识": "PX-1",
    })
    assert not missing and edge["status"] == "已验证", edge
    edge2, _ = graph.register_generic_edge({
        "边ID": "E-OLD-POINT", "源实体": "C", "目标实体": "D",
        "关系类型": "时序关系", "抽取页面": "page-2",
        "原文证据": "", "关联强度": "0.7",
        "外部命名空间": "px-rel", "外部关系标识": "PX-OLD",
    })
    # 核验为有效边。
    graph.run_action(edge2["id"], "验证关系")

    payload = {
        "partner_code": "PARTNER-Y",
        "file_batch": "ACCEPT-1",
        "file_kind": "initial",
        "conflict_policy": "accept_correspondence",
        "declarations": [{
            "external_namespace": "px-rel",
            "external_relation_id": "PX-1",
            "source_page": "page-1",
            "source_entity": "A",
            "target_entity": "B",
            "old_edge_id": "E-OLD-POINT",
            "renumber_basis": "旧号填报错误但选择接纳对应关系",
        }],
    }
    receipt = link.import_partner_file(payload)
    pairing = receipt["pairings"][0]
    assert pairing["claim_status"] == "已附证据", pairing
    assert pairing["attached"] is True
    assert "接纳" in pairing["reason"]
    evidence = graph.edge_evidence_list("E-VERIFIED")
    assert len(evidence) == 1 and evidence[0]["edge_id"] == "E-VERIFIED"
    print("策略 accept_correspondence：冲突留痕但当轮即附证据 ->", pairing["reason"])

    # 多匹配裁决：同页同端点登记两条有效边 -> 待人工裁决，不附证据。
    graph.register_generic_edge({
        "边ID": "E-DUP-1", "源实体": "M", "目标实体": "N",
        "关系类型": "从属关系", "抽取页面": "page-dup",
        "原文证据": "", "关联强度": "0.8",
        "外部命名空间": "px-rel", "外部关系标识": "PX-D1",
    })
    graph.register_generic_edge({
        "边ID": "E-DUP-2", "源实体": "M", "目标实体": "N",
        "关系类型": "从属关系", "抽取页面": "page-dup",
        "原文证据": "", "关联强度": "0.8",
        "外部命名空间": "px-rel", "外部关系标识": "PX-D2",
    })
    receipt2 = link.import_partner_file({
        "partner_code": "PARTNER-Y", "file_batch": "DUP-1",
        "conflict_policy": "await_partner_correction",
        "declarations": [{
            "external_namespace": "px-rel", "external_relation_id": "PX-DX",
            "source_page": "page-dup", "source_entity": "M", "target_entity": "N",
            "old_edge_id": "", "renumber_basis": "",
        }],
    })
    assert receipt2["pairings"][0]["claim_status"] == "待人工裁决"
    assert graph.edge_evidence_list() and all(
        e["edge_id"] not in ("E-DUP-1", "E-DUP-2") for e in graph.edge_evidence_list())
    print("多匹配分支：待人工裁决，且未向任一边附证据")

    # 通用建边入口（无命名空间历史边）-> 待核实出处，核实后生效。
    hist, _ = graph.register_generic_edge({
        "边ID": "E-HIST", "源实体": "H1", "目标实体": "H2",
        "关系类型": "从属关系", "抽取页面": "page-hist",
        "原文证据": "", "关联强度": "0.75",
    })
    assert hist["status"] == "已抽取" and not hist.get("外部命名空间")
    graph.run_action(hist["id"], "验证关系")
    receipt3 = link.import_partner_file({
        "partner_code": "PARTNER-Y", "file_batch": "HIST-1",
        "conflict_policy": "await_partner_correction",
        "declarations": [{
            "external_namespace": "px-rel", "external_relation_id": "PX-H",
            "source_page": "page-hist", "source_entity": "H1", "target_entity": "H2",
            "old_edge_id": "", "renumber_basis": "",
        }],
    })
    assert receipt3["pairings"][0]["claim_status"] == "待核实出处"
    review = graph.review_checklist("待核实出处")
    target = next(r for r in review if r["source_page"] == "page-hist")
    item, msg = graph.verify_historical_provenance(target["id"])
    assert item["review_status"] == "已附证据"
    refreshed = graph.find_edge_by_id("E-HIST")
    assert refreshed["外部命名空间"] == "px-rel"
    assert any(e["edge_id"] == "E-HIST" for e in graph.edge_evidence_list())
    print("历史边分支：待核实出处 -> 核实后补记命名空间并附证据")

    # 证据唯一对应：同一声明不会产生两条证据。
    all_ev = graph.edge_evidence_list()
    claim_ids = [e["claim_id"] for e in all_ev]
    assert len(claim_ids) == len(set(claim_ids))
    print(f"唯一对应校验：{len(all_ev)} 条证据，声明身份无重复")

    # 领域快照包含外部证据统计。
    snap_g = graph.domain_snapshot()
    snap_l = link.domain_snapshot()
    assert "external_evidence" in snap_g and "external_claims" in snap_l
    print("图谱快照 external_evidence:", snap_g["external_evidence"])
    print("知识链接快照 external_claims:", snap_l["external_claims"])
    print("\n服务层补充校验全部通过。")


if __name__ == "__main__":
    main()
