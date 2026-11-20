<template>
  <section class="page" data-module="knowledge-evidence">
    <header class="page-head">
      <div>
        <h2>外部知识声明对接</h2>
        <p class="page-desc">
          合作图谱文件导入：外部关系命名空间与本站关系标识对照，形成原边对应的外部知识声明数据包
        </p>
      </div>
      <div class="page-actions">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="btn"
          :class="{ primary: activeTab === tab.key }"
          type="button"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>
    </header>

    <p v-if="message" class="status-legend" data-testid="evidence-message">{{ message }}</p>

    <!-- 来件导入 -->
    <div v-if="activeTab === 'imports'" class="evidence-panel">
      <h3>外部关系命名空间对照</h3>
      <form class="filter-bar" @submit.prevent="submitNamespace">
        <label class="filter-item">
          <span>外部命名空间</span>
          <input v-model="namespaceForm.external_namespace" data-testid="ns-name" required />
        </label>
        <label class="filter-item">
          <span>本站关系标识</span>
          <input v-model="namespaceForm.local_relation_type" data-testid="ns-local" required />
        </label>
        <label class="filter-item">
          <span>合作方标识</span>
          <input v-model="namespaceForm.partner_code" data-testid="ns-partner" />
        </label>
        <button class="btn" data-testid="ns-submit" type="submit">登记对照</button>
      </form>

      <h3>合作图谱文件导入</h3>
      <form class="filter-bar" @submit.prevent="submitImport">
        <label class="filter-item">
          <span>合作方标识</span>
          <input v-model="importForm.partner_code" data-testid="imp-partner" required />
        </label>
        <label class="filter-item">
          <span>来件批次</span>
          <input v-model="importForm.file_batch" data-testid="imp-batch" required />
        </label>
        <label class="filter-item">
          <span>文件类型</span>
          <select v-model="importForm.file_kind" data-testid="imp-kind">
            <option value="initial">首次件</option>
            <option value="correction">更正件</option>
          </select>
        </label>
        <label class="filter-item">
          <span>冲突策略</span>
          <select v-model="importForm.conflict_policy" data-testid="imp-policy">
            <option value="await_partner_correction">等待外方更正</option>
            <option value="accept_correspondence">接纳对应关系</option>
          </select>
        </label>
        <label class="filter-item" style="flex: 1 1 100%">
          <span>declarations（JSON 数组：来源页、有向端点、换号依据、旧边编号）</span>
          <textarea
            v-model="importForm.declarationsText"
            data-testid="imp-declarations"
            rows="8"
            required
          ></textarea>
        </label>
        <button class="btn primary" data-testid="imp-submit" type="submit">导入来件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr><th>来件ID</th><th>合作方</th><th>批次</th><th>类型</th><th>冲突策略</th><th>声明数</th><th>接收时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in imports" :key="String(row.id)" data-testid="import-row">
            <td>{{ row.id }}</td>
            <td>{{ row.partner_code }}</td>
            <td>{{ row.file_batch }}</td>
            <td>{{ row.file_kind === 'correction' ? '更正件' : '首次件' }}</td>
            <td>{{ row.conflict_policy === 'accept_correspondence' ? '接纳对应关系' : '等待外方更正' }}</td>
            <td>{{ row.declaration_count }}</td>
            <td>{{ row.received_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 声明数据包 -->
    <div v-else-if="activeTab === 'claims'" class="evidence-panel">
      <h3>外部知识声明数据包（同一声明身份只认一条，原始来件全部留存）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>声明身份</th><th>命名空间</th><th>外部关系标识</th><th>来源页</th>
            <th>有向端点</th><th>旧边编号</th><th>状态</th><th>配对边</th><th>修订次数</th><th>来件</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in claims" :key="String(row.claim_id)" data-testid="claim-row">
            <td>{{ row.claim_id }}</td>
            <td>{{ row.external_namespace }}</td>
            <td>{{ row.external_relation_id }}</td>
            <td>{{ row.source_page }}</td>
            <td>{{ row.source_entity }} → {{ row.target_entity }}</td>
            <td>{{ row.old_edge_id || '—' }}</td>
            <td>{{ row.claim_status }}</td>
            <td>{{ row.matched_edge_id || '—' }}</td>
            <td>{{ row.revision_count }}</td>
            <td>{{ (row.source_file_ids || []).join(', ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 边证据清单 -->
    <div v-else-if="activeTab === 'evidence'" class="evidence-panel">
      <h3>边证据清单（每项确认证据唯一对应一条有效有向边）</h3>
      <form class="filter-bar" @submit.prevent="loadEvidence">
        <label class="filter-item">
          <span>按边ID过滤</span>
          <input v-model="edgeFilter" data-testid="ev-filter" placeholder="留空查看全部" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr><th>证据ID</th><th>本站边</th><th>命名空间</th><th>外部关系标识</th><th>来源页</th><th>有向端点</th><th>旧边编号</th><th>附证依据</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in evidence" :key="String(row.evidence_id)" data-testid="evidence-row">
            <td>{{ row.evidence_id }}</td>
            <td>{{ row.edge_id }}</td>
            <td>{{ row.external_namespace }}</td>
            <td>{{ row.external_relation_id }}</td>
            <td>{{ row.source_page }}</td>
            <td>{{ row.source_entity }} → {{ row.target_entity }}</td>
            <td>{{ row.old_edge_id || '—' }}</td>
            <td>{{ row.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 图谱复核清单 -->
    <div v-else-if="activeTab === 'review'" class="evidence-panel">
      <h3>图谱复核清单（导入结果回写）</h3>
      <form class="filter-bar" @submit.prevent="loadReview">
        <label class="filter-item">
          <span>按状态过滤</span>
          <input v-model="reviewFilter" data-testid="rv-filter" placeholder="如：待核实出处" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr><th>复核ID</th><th>状态</th><th>声明身份</th><th>配对边</th><th>有向端点</th><th>旧边编号</th><th>说明</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in review" :key="String(row.id)" data-testid="review-row">
            <td>{{ row.id }}</td>
            <td>{{ row.review_status }}</td>
            <td>{{ row.claim_id }}</td>
            <td>{{ row.edge_id || '—' }}</td>
            <td>{{ row.source_entity }} → {{ row.target_entity }}</td>
            <td>{{ row.old_edge_id || '—' }}</td>
            <td>{{ row.detail }}</td>
            <td class="row-actions">
              <button
                v-if="row.review_status === '待核实出处'"
                class="link"
                type="button"
                :data-testid="`verify-${row.id}`"
                @click="submitProvenance(Number(row.id))"
              >
                核实出处
              </button>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 换号建边入口 -->
    <div v-else class="evidence-panel">
      <h3>建边入口：登记同页有向边换号证据（另一处通用入口在关系图谱页）</h3>
      <form class="filter-bar" @submit.prevent="submitRenumber">
        <label class="filter-item">
          <span>本站边ID</span>
          <input v-model="renumberForm.edge_id" data-testid="rn-edge" required />
        </label>
        <label class="filter-item">
          <span>源实体</span>
          <input v-model="renumberForm.source_entity" data-testid="rn-src" required />
        </label>
        <label class="filter-item">
          <span>目标实体</span>
          <input v-model="renumberForm.target_entity" data-testid="rn-tgt" required />
        </label>
        <label class="filter-item">
          <span>关系类型</span>
          <input v-model="renumberForm.relation_type" data-testid="rn-type" required />
        </label>
        <label class="filter-item">
          <span>来源页</span>
          <input v-model="renumberForm.source_page" data-testid="rn-page" required />
        </label>
        <label class="filter-item">
          <span>外部命名空间</span>
          <input v-model="renumberForm.external_namespace" data-testid="rn-ns" required />
        </label>
        <label class="filter-item">
          <span>外部关系标识</span>
          <input v-model="renumberForm.external_relation_id" data-testid="rn-ext" required />
        </label>
        <label class="filter-item">
          <span>旧边编号（可空）</span>
          <input v-model="renumberForm.old_edge_id" data-testid="rn-old" />
        </label>
        <button class="btn primary" data-testid="rn-submit" type="submit">登记并同步已核定证据</button>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  importPartnerFile,
  listClaims,
  listEdgeEvidence,
  listPartnerImports,
  listReviewChecklist,
  registerNamespace,
  registerRenumberedEdge,
  verifyProvenance,
} from '@/api/backend-service'

type Row = Record<string, any>

const tabs = [
  { key: 'imports', label: '来件导入' },
  { key: 'claims', label: '声明数据包' },
  { key: 'evidence', label: '边证据清单' },
  { key: 'review', label: '复核清单' },
  { key: 'renumber', label: '换号建边' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('imports')
const message = ref('')
const imports = ref<Row[]>([])
const claims = ref<Row[]>([])
const evidence = ref<Row[]>([])
const review = ref<Row[]>([])
const edgeFilter = ref('')
const reviewFilter = ref('')

const emptyImport = () => ({
  partner_code: '',
  file_batch: '',
  file_kind: 'initial',
  conflict_policy: 'await_partner_correction',
  declarationsText: '[]',
})
const importForm = ref(emptyImport())

const namespaceForm = ref({
  external_namespace: '',
  local_relation_type: '',
  partner_code: '',
})

const emptyRenumber = () => ({
  edge_id: '',
  source_entity: '',
  target_entity: '',
  relation_type: '',
  source_page: '',
  external_namespace: '',
  external_relation_id: '',
  old_edge_id: '',
})
const renumberForm = ref(emptyRenumber())

async function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  message.value = ''
  await reloadActive()
}

async function reloadActive() {
  if (activeTab.value === 'imports') {
    imports.value = (await listPartnerImports()).items
  } else if (activeTab.value === 'claims') {
    claims.value = (await listClaims()).items
  } else if (activeTab.value === 'evidence') {
    await loadEvidence()
  } else if (activeTab.value === 'review') {
    await loadReview()
  }
}

async function loadEvidence() {
  evidence.value = (await listEdgeEvidence(edgeFilter.value.trim())).items
}

async function loadReview() {
  review.value = (await listReviewChecklist(reviewFilter.value.trim())).items
}

async function submitNamespace() {
  message.value = ''
  const result: any = await registerNamespace({ ...namespaceForm.value })
  message.value = result.detail
    ? `对照登记失败：${result.detail}`
    : `命名空间 ${namespaceForm.value.external_namespace} 对照已登记`
  namespaceForm.value = { external_namespace: '', local_relation_type: '', partner_code: '' }
}

async function submitImport() {
  message.value = ''
  let declarations: unknown
  try {
    declarations = JSON.parse(importForm.value.declarationsText)
  } catch {
    message.value = 'declarations 不是合法 JSON'
    return
  }
  if (!Array.isArray(declarations)) {
    message.value = 'declarations 必须是数组'
    return
  }
  const result: any = await importPartnerFile({
    partner_code: importForm.value.partner_code,
    file_batch: importForm.value.file_batch,
    file_kind: importForm.value.file_kind,
    conflict_policy: importForm.value.conflict_policy,
    declarations,
  })
  message.value = result.detail
    ? `导入被拒：${result.detail}`
    : `${result.message}；状态分布 ${JSON.stringify(result.status_counts)}`
  importForm.value = emptyImport()
  await reloadActive()
}

async function submitProvenance(reviewId: number) {
  message.value = ''
  const result: any = await verifyProvenance(reviewId)
  message.value = result.detail ? `核实失败：${result.detail}` : `出处核实通过，证据 ${result.message} 已生效`
  await loadReview()
}

async function submitRenumber() {
  message.value = ''
  const payload = { ...renumberForm.value }
  if (!payload.old_edge_id) payload.old_edge_id = null as unknown as string
  const result: any = await registerRenumberedEdge(payload)
  message.value = result.detail
    ? `登记失败：${result.detail}`
    : `${result.message}；同步声明 ${result.synced_claim_ids.join(', ') || '无'}`
  renumberForm.value = emptyRenumber()
}

onMounted(reloadActive)
</script>
