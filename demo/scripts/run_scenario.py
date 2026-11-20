"""外部知识声明对接全链路演示。

运行前提：后端已在 127.0.0.1:8000 启动（cd backend && ./run.sh）。
本脚本只使用标准库，并以 python -I 运行，避免来件目录中的同名模块干扰。

场景对应需求：
  1. 导入一份带旧号的合作方文件（首次件，5 条声明，覆盖五种处置分支）
  2. 图谱登记同页有向边换号证据 + 另一条同名反向边
  3. 核实历史边出处后对应来件生效
  4. 并发提交首次件/更正件时只认一个声明身份，原始来件都保存
  5. 再次提交更正文件，查看边证据清单与导入回执中实际配对的数据
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
DATA_DIR = "/workspace/demo/partner-files"


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise SystemExit(f"接口 {method} {path} 返回 {exc.code}：{body}") from exc


def load_file(name: str) -> dict:
    with open(f"{DATA_DIR}/{name}", "r", encoding="utf-8") as handle:
        return json.load(handle)


def show(title: str, value: object) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    # 0. 登记外部关系命名空间 ↔ 本站关系标识对照。
    ns = call("POST", "/api/knowledge-evidence/namespaces", {
        "external_namespace": "px-rel",
        "local_relation_type": "从属关系",
        "partner_code": "PARTNER-X",
    })
    show("步骤0 命名空间对照登记", ns)

    # 1. 准备本站数据：一条带命名空间的有效边 + 两条无命名空间的历史边。
    def create_edge(values: dict) -> dict:
        result = call("POST", "/api/relation_graph", {"values": values})
        if not result.get("ok") or not result.get("entry"):
            raise SystemExit(f"本站边登记失败：{result}")
        return result["entry"]

    beta = create_edge({
        "边ID": "EDGE-BETA-01", "源实体": "实体丙", "目标实体": "实体丁",
        "关系类型": "从属关系", "抽取页面": "https://site.example.com/page/beta",
        "原文证据": "beta 页面共现", "关联强度": "0.88",
        "外部命名空间": "px-rel", "外部关系标识": "PX-R-9003",
    })
    alpha_hist = create_edge({
        "边ID": "OLD-E-7001", "源实体": "实体甲", "目标实体": "实体乙",
        "关系类型": "从属关系", "抽取页面": "https://site.example.com/page/alpha",
        "原文证据": "alpha 页面历史抽取", "关联强度": "0.81",
    })
    gamma_hist = create_edge({
        "边ID": "EDGE-GAMMA-01", "源实体": "实体戊", "目标实体": "实体己",
        "关系类型": "从属关系", "抽取页面": "https://site.example.com/page/gamma",
        "原文证据": "gamma 页面历史抽取", "关联强度": "0.83",
    })
    other = create_edge({
        "边ID": "OLD-E-7003", "源实体": "实体壬", "目标实体": "实体癸",
        "关系类型": "时序关系", "抽取页面": "https://site.example.com/page/other",
        "原文证据": "旧号实际指向的另一条边", "关联强度": "0.70",
        "外部命名空间": "px-rel", "外部关系标识": "PX-R-OTHER",
    })
    # 无外部命名空间的历史边走既有状态流转动作核验为有效有向边。
    for entry in (beta, alpha_hist, gamma_hist, other):
        if entry["status"] != "已验证":
            call("POST", f"/api/relation_graph/{entry['id']}/actions", {"action": "验证关系"})
    print("步骤1 本站边已登记并核验：EDGE-BETA-01（带命名空间）、OLD-E-7001 / EDGE-GAMMA-01（历史边）、OLD-E-7003（旧号实际指向）")

    # 2. 导入首次件。
    first_receipt = call(
        "POST", "/api/knowledge-evidence/partner-imports", load_file("partner-initial-b001.json"))
    show("步骤2 首次件导入回执（实际配对）", {
        "file_batch": first_receipt["file_batch"],
        "saved_file_id": first_receipt["saved_file_id"],
        "status_counts": first_receipt["status_counts"],
        "pairings": first_receipt["pairings"],
    })

    # 3. 图谱复核清单（导入结果回写）。
    review = call("GET", "/api/knowledge-evidence/review-checklist")
    show("步骤3 图谱复核清单", review)

    # 4. 图谱登记同页有向边换号证据（建边入口一），并登记同名反向边。
    renumber = call("POST", "/api/knowledge-evidence/edges/register-renumber", {
        "edge_id": "EDGE-ALPHA-NEW-01",
        "source_entity": "实体甲",
        "target_entity": "实体乙",
        "relation_type": "从属关系",
        "source_page": "https://site.example.com/page/alpha",
        "external_namespace": "px-rel",
        "external_relation_id": "PX-R-9001",
        "old_edge_id": "OLD-E-7001",
        "origin_evidence": "alpha 页面换号登记，旧边 OLD-E-7001 已过期",
    })
    show("步骤4a 换号有向边登记（旧边过期 + 等待中声明自动重核）", renumber)

    reverse = call("POST", "/api/knowledge-evidence/edges/register-renumber", {
        "edge_id": "EDGE-ALPHA-NEW-02",
        "source_entity": "实体乙",
        "target_entity": "实体甲",
        "relation_type": "从属关系",
        "source_page": "https://site.example.com/page/alpha",
        "external_namespace": "px-rel",
        "external_relation_id": "PX-R-9001",
        "old_edge_id": None,
        "origin_evidence": "同页同名关系的反向有向边",
    })
    show("步骤4b 同名反向有向边登记", reverse)

    # 5. 核实历史边出处：gamma 边的待核实来件生效。
    review_gamma = call(
        "GET",
        "/api/knowledge-evidence/review-checklist?status="
        + urllib.parse.quote("待核实出处"),
    )
    target = next(
        (item for item in review_gamma["items"]
         if item["source_page"] == "https://site.example.com/page/gamma"),
        None,
    )
    if target is None:
        raise SystemExit("未找到 gamma 历史边的待核实条目")
    provenance = call(
        "POST", f"/api/knowledge-evidence/review-checklist/{target['id']}/verify-provenance")
    show("步骤5 历史边出处核实（来件生效）", provenance)

    # 6. 并发语义演示：同一首次件再提交一次——只认一个声明身份，但原始来件仍保存。
    duplicate = call(
        "POST", "/api/knowledge-evidence/partner-imports", load_file("partner-initial-b001.json"))
    show("步骤6 首次件重复提交（身份去重、来件留存）", {
        "saved_file_id": duplicate["saved_file_id"],
        "updated_claim_identities": duplicate["updated_claim_identities"],
        "total_claims_after_duplicate": len(call("GET", "/api/knowledge-evidence/claims")["items"]),
        "partner_files": call("GET", "/api/knowledge-evidence/partner-imports")["items"],
    })

    # 7. 导入更正件：冲突声明更正后自动配对，已附声明保持同一身份。
    correction_receipt = call(
        "POST", "/api/knowledge-evidence/partner-imports", load_file("partner-correction-b002.json"))
    show("步骤7 更正件导入回执（实际配对）", {
        "file_batch": correction_receipt["file_batch"],
        "saved_file_id": correction_receipt["saved_file_id"],
        "status_counts": correction_receipt["status_counts"],
        "updated_claim_identities": correction_receipt["updated_claim_identities"],
        "pairings": correction_receipt["pairings"],
    })

    # 8. 最终核对：边证据清单 + 声明数据包 + 唯一对应关系。
    evidence = call("GET", "/api/knowledge-evidence/edge-evidence")
    claims = call("GET", "/api/knowledge-evidence/claims")
    edge_to_evidence: dict[str, list[str]] = {}
    for item in evidence["items"]:
        edge_to_evidence.setdefault(item["edge_id"], []).append(item["evidence_id"])
    uniqueness = {
        edge_id: ids for edge_id, ids in edge_to_evidence.items()
    }
    show("步骤8a 边证据清单（每条证据唯一对应一条有效有向边）", {
        "total": evidence["total"],
        "items": evidence["items"],
        "edge_to_evidence": uniqueness,
    })
    show("步骤8b 外部知识声明数据包（声明身份与当前状态）", [
        {
            "claim_id": row["claim_id"],
            "claim_status": row["claim_status"],
            "matched_edge_id": row["matched_edge_id"],
            "revision_count": row["revision_count"],
            "current_file_batch": row["current_file_batch"],
            "source_file_ids": row["source_file_ids"],
        }
        for row in claims["items"]
    ])

    # 9. 断言关键不变量。
    errors: list[str] = []
    evidence_claim_ids = [item["claim_id"] for item in evidence["items"]]
    if len(evidence_claim_ids) != len(set(evidence_claim_ids)):
        errors.append("存在一条声明对应多条证据，违反唯一对应约束")
    if any(len(ids) > 1 for ids in edge_to_evidence.values()):
        errors.append("存在一条边被多条证据重复挂载")
    files = call("GET", "/api/knowledge-evidence/partner-imports")["items"]
    if len(files) != 3:
        errors.append(f"原始来件应保存 3 份（首次件×2 + 更正件），实际 {len(files)} 份")
    claim_9003 = next(row for row in claims["items"] if row["external_relation_id"] == "PX-R-9003")
    if claim_9003["claim_status"] != "已附证据":
        errors.append("更正后 PX-R-9003 应已附证据")
    if claim_9003["matched_edge_id"] != "EDGE-BETA-01":
        errors.append("PX-R-9003 应配对到 EDGE-BETA-01")
    if errors:
        raise SystemExit("不变量校验失败：" + "；".join(errors))
    print("\n全部不变量校验通过：证据唯一对应、来件全留存、声明身份唯一、更正后正确配对。")


if __name__ == "__main__":
    main()
