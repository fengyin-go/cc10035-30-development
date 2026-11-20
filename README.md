# Web语义抽取与内容理解中心

面向Web结构化数据采集场景，提供页面DOM解析、实体识别、关系抽取、内容分类和知识图谱构建的语义抽取平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| DOM解析 | `dom_parser` | 解析配置 | 配置名称、目标URI、解析引擎 |
| 实体抽取 | `entity_extract` | 实体条目 | 实体ID、实体类型、实体名称 |
| 关系图谱 | `relation_graph` | 关系边 | 边ID、源实体、目标实体 |
| 内容分类 | `content_classifier` | 分类标签 | 标签ID、页面URI、一级分类 |
| 模板规则 | `template_rule` | 规则模板 | 模板名称、适用站点、提取字段 |
| 文本分块 | `text_segment` | 文本块 | 块ID、来源页面、块类型 |
| 情感标注 | `sentiment_tag` | 情感记录 | 记录ID、文本片段、情感倾向 |
| Schema对齐 | `schema_align` | 对齐规则 | 规则名称、源Schema、目标Schema |
| 种子调度 | `feed_scheduler` | 调度任务 | 任务名称、URL种子、抓取深度 |
| 质量检查 | `quality_check` | 检查规则 | 规则名称、检查字段、检查类型 |
| 探针选择 | `probe_selector` | 探针配置 | 探针名称、目标页面、选择器列表 |
| 页面快照 | `page_snapshot` | 快照记录 | 快照ID、页面URI、DOM哈希 |
| 抽取指标 | `extract_metric` | 指标记录 | 记录时间、所属任务、成功页面数 |
| 语义结果 | `nlu_result` | 语义记录 | 记录ID、输入文本、意图标签 |
| 知识链接 | `knowledge_link` | 链接记录 | 链接ID、源实体、外部URI |
| 输出目标 | `output_target` | 输出配置 | 配置名称、输出类型、目标地址 |
| 抽取工坊 | `extract_studio` | 交互任务 | 任务名称、示例页面、标注区域 |
| 聚合视图 | `aggregate_view` | 视图配置 | 视图名称、统计维度、聚合字段 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 外部知识声明对接

知识链接模块在通用资源路由之外，额外提供合作图谱文件导入能力，固定前缀
`/api/knowledge-evidence`（路由见 `backend/app/routers/knowledge_evidence.py`，
领域逻辑在 `services/knowledge_link.py` 与 `services/relation_graph.py`）：

- `POST /namespaces`：登记外部关系命名空间 ↔ 本站关系标识对照。
- `POST /partner-imports`：导入合作方来件（首次件/更正件），回执含每条声明
  实际配对的边、状态与原因；原始来件无条件保存，可按 id 完整取回。
- `GET /claims`：外部知识声明数据包。声明身份由合作方+命名空间+外部关系标识+
  来源页+有向端点哈希得到，并发提交首次件与更正件只认一个身份，修订留 history。
- `GET /review-checklist`：图谱复核清单，导入结果逐条回写；
  `POST /review-checklist/{id}/verify-provenance` 核实历史边出处后来件生效。
- `GET /edge-evidence`：边证据清单，每项确认证据唯一对应本站一条有效有向边。
- `POST /edges/register-renumber`：建边入口一（换号登记，旧边置过期并自动
  重核等待中的声明）；通用 `POST /api/relation_graph` 为建边入口二，两处入口
  同步取得已核定外部证据。

声明处置分支：已附证据 / 待匹配边 / 待核实出处（历史边无外部命名空间）/
待外方更正（旧号指向与核验属性冲突，可按 `conflict_policy` 选择接纳或等待更正）/
待人工裁决（同页同端点匹配多条边）/ 命名空间未登记。

端到端演示（后端启动后运行，数据与脚本分目录，脚本以 `python -I` 执行）：

```bash
backend/.venv/bin/python -I demo/scripts/run_scenario.py   # HTTP 全链路 + 不变量断言
backend/.venv/bin/python -I demo/scripts/service_checks.py # 服务层分支补充校验
```

领域：数据工程
子方向：数据采集、爬虫与RPA
