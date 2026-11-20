"""业务路由汇总：固定路径的外部声明路由在前，通配资源路由在后。"""
from __future__ import annotations

from app.routers import knowledge_evidence, resource

ROUTERS = [knowledge_evidence, resource]
