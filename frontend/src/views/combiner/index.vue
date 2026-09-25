<template>
  <section class="page" data-module="combiner">
    <header class="page-head">
      <div>
        <h2>汇流箱管理管理</h2>
        <p class="page-desc">维护汇流箱，围绕汇流箱编号、接入组串数、直流电压做登记、筛选、支路异常定位与状态流转。</p>
      </div>
      <div class="page-actions">
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

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>汇流箱编号</span>
        <input v-model="filters.keyword" placeholder="按汇流箱编号检索" />
      </label>
      <label class="filter-item">
        <span>运行状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>定位方阵</span>
        <input v-model="locateArrays" placeholder="跨方阵用逗号分隔，留空为全部" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <button class="btn" :class="{ primary: locateActive }" type="button" @click="toggleLocate">
        {{ locateActive ? '退出支路定位' : '支路异常定位' }}
      </button>
    </form>

    <p v-if="locateActive" class="locate-hint">
      支路异常定位中：支路异常设备置顶并标出异常支路号，按接入组串数与直流电压排序；直流电压超出
      {{ voltageRangeText }} 单独着色；同一台设备跨方阵只显示一次。筛选或刷新后定位结果保持不变。
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>异常支路号</th>
          <th v-if="locateActive">定位说明</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-branch-abnormal': row.status === '支路异常' }">
          <td v-for="column in columns" :key="column" :class="cellClass(column, row)">
            {{ displayCell(column, row) }}
          </td>
          <td :class="{ 'branch-abnormal': branchesOf(row).length > 0 }">{{ branchesText(row) }}</td>
          <td v-if="locateActive">{{ row['定位说明'] || '—' }}</td>
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
          <td :colspan="columns.length + (locateActive ? 3 : 2)" class="empty-state">暂无汇流箱管理数据，可先登记汇流箱</td>
        </tr>
      </tbody>
    </table>

    <aside v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>汇流箱详情：{{ detail['汇流箱编号'] ?? detail.id }}</h3>
        <button class="btn ghost" type="button" @click="detail = null">关闭</button>
      </header>
      <div class="detail-grid">
        <div v-for="column in columns" :key="column" class="detail-item">
          <span>{{ column }}</span>
          <strong :class="cellClass(column, detail)">{{ displayCell(column, detail) }}</strong>
        </div>
        <div class="detail-item">
          <span>异常支路号</span>
          <strong :class="{ 'branch-abnormal': branchesOf(detail).length > 0 }">{{ branchesText(detail) }}</strong>
        </div>
        <div class="detail-item">
          <span>定位说明</span>
          <strong>{{ detail['定位说明'] || '—' }}</strong>
        </div>
      </div>
    </aside>

    <footer class="page-foot">
      <span>共 {{ total }} 条汇流箱管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type CellValue = string | number | boolean | number[] | null | undefined
type Row = Record<string, CellValue> & { id: number | string }

const ENDPOINT = '/api/combiner'
const columns = ["汇流箱编号", "接入组串数", "直流电压", "输出电流", "防雷模块状态", "所属方阵", "安装位置", "运行状态"]
const actions = ["确认正常", "登记支路异常", "更换设备"]
const statuses = ["待巡检", "正常", "支路异常", "已更换"]
const voltageRangeText = '500V～1500V'
const LOCATE_STORAGE_KEY = 'combiner-locate-state'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const detail = ref<Row | null>(null)
const locateActive = ref(false)
const locateArrays = ref('')

const stats = computed(() => [
  { label: '正常汇流箱', value: rows.value.filter((row) => row.status === '正常').length },
  { label: '支路异常', value: rows.value.filter((row) => row.status === '支路异常').length },
  { label: '待巡检汇流箱', value: rows.value.filter((row) => row.status === '待巡检').length },
])

function branchesOf(row: Row): number[] {
  const value = row['异常支路号']
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === 'number') : []
}

function branchesText(row: Row): string {
  const branches = branchesOf(row)
  return branches.length ? branches.join('、') : '—'
}

function displayCell(column: string, row: Row): string {
  const value = row[column]
  if (Array.isArray(value)) {
    return value.length ? value.join('、') : '—'
  }
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return String(value)
}

function cellClass(column: string, row: Row): string {
  if (column === '直流电压' && row['电压越限'] === true) {
    return 'cell-voltage-violation'
  }
  return ''
}

function saveLocateState() {
  const state = { active: locateActive.value, arrays: locateArrays.value }
  window.localStorage.setItem(LOCATE_STORAGE_KEY, JSON.stringify(state))
}

function restoreLocateState() {
  try {
    const raw = window.localStorage.getItem(LOCATE_STORAGE_KEY)
    if (!raw) {
      return
    }
    const state = JSON.parse(raw) as { active?: boolean; arrays?: string }
    locateActive.value = Boolean(state.active)
    locateArrays.value = typeof state.arrays === 'string' ? state.arrays : ''
  } catch {
    window.localStorage.removeItem(LOCATE_STORAGE_KEY)
  }
}

function toggleLocate() {
  locateActive.value = !locateActive.value
  saveLocateState()
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
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
  const values: Record<string, string> = { action }
  if (action === '登记支路异常') {
    const current = branchesText(row)
    const input = window.prompt('请输入异常支路号（多个用逗号分隔）', current === '—' ? '' : current)
    if (input === null) {
      return
    }
    if (input.trim()) {
      values['异常支路号'] = input.trim()
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '汇流箱管理动作未生效，请稍后重试')
    }
    errorMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱管理操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) {
    query.set('keyword', filters.value.keyword)
  }
  if (filters.value.status) {
    query.set('status', filters.value.status)
  }
  if (locateActive.value) {
    query.set('locate', '1')
    if (locateArrays.value.trim()) {
      query.set('arrays', locateArrays.value.trim())
    }
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('汇流箱列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '汇流箱管理列表读取失败'
  }
}

onMounted(() => {
  restoreLocateState()
  void reload()
})
</script>
