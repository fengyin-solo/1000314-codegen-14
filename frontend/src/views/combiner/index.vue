<template>
  <section class="page" data-module="combiner">
    <header class="page-head">
      <div>
        <h2>汇流箱管理</h2>
        <p class="page-desc">
          维护汇流箱，围绕汇流箱编号、接入组串数、直流电压、输出电流做登记、筛选与状态流转；
          支路异常设备自动置顶并标注异常支路号，直流电压超出正常区间的单独着色。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" :class="{ primary: locateMode }" type="button" @click="toggleLocate">
          {{ locateMode ? '退出跨方阵定位' : '跨方阵定位支路异常' }}
        </button>
        <button class="btn primary" type="button" @click="openCreate">登记汇流箱</button>
        <button class="btn" type="button" @click="exportRows">导出汇流箱管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="snapshot" class="locate-banner">
      <span>
        已保留上次定位结果：{{ snapshot.at }} 定位到 {{ snapshot.total }} 台支路异常设备（{{ snapshot.labels }}），
        当前列表命中 {{ visibleSnapshotCount }} 台；切换筛选或刷新页面后结果仍然保留。
      </span>
      <button class="link" type="button" @click="clearLocate">清除定位结果</button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>汇流箱编号</span>
        <input v-model="filters.keyword" placeholder="按汇流箱编号检索" />
      </label>
      <label class="filter-item">
        <span>所属方阵</span>
        <input v-model="filters.array" placeholder="按所属方阵检索" />
      </label>
      <label class="filter-item">
        <span>运行状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-abnormal': isAbnormal(row) }">
          <td>{{ row['汇流箱编号'] ?? '—' }}</td>
          <td>
            <span v-if="row['接入组串数'] != null">{{ row['接入组串数'] }}</span>
            <span v-else class="cell-missing">{{ row['组串数缺失原因'] ?? '未采集' }}</span>
          </td>
          <td>
            <span v-if="row['直流电压'] != null" :class="voltageClass(row)">{{ row['直流电压'] }} V</span>
            <span v-else class="cell-missing">未采集</span>
          </td>
          <td>{{ row['输出电流'] ?? '—' }}</td>
          <td>{{ row['防雷模块状态'] ?? '—' }}</td>
          <td>{{ row['所属方阵'] ?? '—' }}</td>
          <td>{{ row['安装位置'] ?? '—' }}</td>
          <td>{{ row['运行状态'] ?? '—' }}</td>
          <td>
            <template v-if="branchList(row).length">
              <span v-for="branch in branchList(row)" :key="branch" class="branch-badge">{{ branch }} 号支路</span>
            </template>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无汇流箱管理数据，可先登记汇流箱</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条汇流箱管理记录</span>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>汇流箱详情：{{ detail['汇流箱编号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd :class="detailClass(field)">{{ detailText(field) }}</dd>
          </template>
        </dl>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = {
  id: number | string
  status?: string
  [key: string]: string | number | number[] | null | undefined
}

interface LocateSnapshot {
  at: string
  total: number
  ids: string[]
  labels: string
}

const ENDPOINT = '/api/combiner'
const STORAGE_KEY = 'combiner-locate-v1'
const columns = ["汇流箱编号", "接入组串数", "直流电压", "输出电流", "防雷模块状态", "所属方阵", "安装位置", "运行状态", "异常支路号"]
const actions = ["确认正常", "登记支路异常", "更换设备"]
const statuses = ["待巡检", "正常", "支路异常", "已更换"]
const detailFields = [...columns, "电压状态"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref({ keyword: '', array: '', status: '' })
const locateMode = ref(false)
const snapshot = ref<LocateSnapshot | null>(null)
const detail = ref<Row | null>(null)

const stats = computed(() => [
  { label: '正常汇流箱', value: rows.value.filter((row) => row.status === '正常').length },
  { label: '支路异常', value: rows.value.filter((row) => row.status === '支路异常').length },
  { label: '待巡检汇流箱', value: rows.value.filter((row) => row.status === '待巡检').length },
])

const visibleSnapshotCount = computed(() => {
  if (!snapshot.value) return 0
  const ids = new Set(snapshot.value.ids)
  return rows.value.filter((row) => ids.has(String(row.id))).length
})

function isAbnormal(row: Row) {
  return row.status === '支路异常'
}

function branchList(row: Row): number[] {
  const value = row['异常支路号']
  return Array.isArray(value) ? value : []
}

function voltageClass(row: Row) {
  if (row['电压状态'] === '偏高') return 'cell-voltage-high'
  if (row['电压状态'] === '偏低') return 'cell-voltage-low'
  return ''
}

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as { locateMode?: boolean; snapshot?: LocateSnapshot }
    locateMode.value = saved.locateMode === true
    snapshot.value = saved.snapshot ?? null
  } catch {
    // 本地缓存损坏时按未定位处理，不影响列表加载
  }
}

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ locateMode: locateMode.value, snapshot: snapshot.value }))
}

function toggleLocate() {
  locateMode.value = !locateMode.value
  persist()
  void reload()
}

function clearLocate() {
  snapshot.value = null
  locateMode.value = false
  persist()
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', array: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '汇流箱登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const values: Record<string, unknown> = { action }
  if (action === '登记支路异常') {
    const input = window.prompt(
      '请输入异常支路号（多个用逗号分隔，如 3,7）；留空表示暂未定位到具体支路',
      branchList(row).join('，')
    )
    if (input === null) return
    if (input.trim()) values['异常支路号'] = input.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json()) as { ok?: boolean; message?: string; detail?: string }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message ?? payload.detail ?? '汇流箱管理动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱管理操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('汇流箱详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱详情读取失败'
  }
}

function detailClass(field: string) {
  const current = detail.value
  if (!current) return ''
  if (field === '异常支路号' && branchList(current).length) return 'branch-text'
  if (field === '直流电压') {
    if (current['电压状态'] === '偏高') return 'cell-voltage-high'
    if (current['电压状态'] === '偏低') return 'cell-voltage-low'
  }
  if (field === '接入组串数' && current['接入组串数'] == null) return 'cell-missing'
  return ''
}

function detailText(field: string): string {
  const current = detail.value
  if (!current) return '—'
  if (field === '异常支路号') {
    const branches = branchList(current)
    return branches.length ? branches.map((branch) => `${branch} 号支路`).join('、') : '—'
  }
  if (field === '接入组串数') {
    const value = current['接入组串数']
    return value != null ? String(value) : String(current['组串数缺失原因'] ?? '未采集')
  }
  if (field === '直流电压') {
    const value = current['直流电压']
    return value != null ? `${value} V` : '未采集'
  }
  const value = current[field]
  return value != null && value !== '' ? String(value) : '—'
}

function dedupeRows(items: Row[]): Row[] {
  // 跨方阵定位时同一台设备可能被多个方阵视图各捞一次，按 id 去重，只显示一遍。
  const seen = new Set<string>()
  return items.filter((row) => {
    const key = String(row.id)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.array) query.set('array', filters.value.array)
  if (filters.value.status) query.set('status', filters.value.status)
  if (locateMode.value) {
    query.set('locate', 'true')
    query.set('size', '200')
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('汇流箱列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = dedupeRows(payload.items ?? [])
    total.value = payload.total ?? rows.value.length
    if (locateMode.value) {
      const abnormal = rows.value.filter(isAbnormal)
      snapshot.value = {
        at: new Date().toLocaleString(),
        total: abnormal.length,
        ids: abnormal.map((row) => String(row.id)),
        labels: abnormal.map((row) => String(row['汇流箱编号'])).join('、') || '无',
      }
      persist()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱管理列表读取失败'
  }
}

onMounted(() => {
  loadPersisted()
  void reload()
})
</script>

<style scoped>
.filter-item input,
.filter-item select {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
}
.row-abnormal td {
  background: #fef3f2;
}
.cell-voltage-high {
  color: #b42318;
  font-weight: 600;
}
.cell-voltage-low {
  color: #b54708;
  font-weight: 600;
}
.cell-missing {
  color: #b54708;
}
.branch-badge {
  display: inline-block;
  margin: 0 4px 2px 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: #fee4e2;
  color: #b42318;
  font-size: 12px;
  font-weight: 600;
}
.branch-text {
  color: #b42318;
  font-weight: 600;
}
.locate-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid #fecdca;
  border-radius: 8px;
  background: #fffbfa;
  color: #b42318;
  font-size: 13px;
}
.ok-text {
  color: #067647;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 520px;
  max-width: 90vw;
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px 12px;
  margin: 12px 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
