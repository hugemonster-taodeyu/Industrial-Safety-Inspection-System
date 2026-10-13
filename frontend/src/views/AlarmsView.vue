<template>
  <div>
    <h1 class="page-title">报警记录</h1>
    <label class="field filter">检测项
      <select v-model="code" @change="load">
        <option value="">全部</option>
        <option v-for="item in detections" :key="item.code" :value="item.code">
          {{ item.code }}. {{ item.title }}
        </option>
      </select>
    </label>
    <table>
      <thead>
        <tr>
          <th>时间</th><th>检测项</th><th>描述</th><th>关联人员</th><th>环境</th><th>模拟</th><th>抓拍</th><th>确认</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!alarms.length">
          <td colspan="8" class="empty">暂无报警记录</td>
        </tr>
        <tr v-for="item in alarms" :key="item.id">
          <td>{{ item.time }}</td>
          <td>{{ item.code }}. {{ item.title }}</td>
          <td style="color: var(--danger); font-weight: 650">{{ item.detail }}</td>
          <td>{{ item.person }}</td>
          <td>{{ item.stage }}</td>
          <td>{{ item.simulated ? "是" : "否" }}</td>
          <td>
            <a v-if="item.snapshot_url" :href="item.snapshot_url" target="_blank">
              <img class="shot" :src="item.snapshot_url" alt="抓拍" />
            </a>
            <span v-else>—</span>
          </td>
          <td>
            <span v-if="item.acknowledged">已确认</span>
            <button v-else class="btn ghost" type="button" @click="acknowledge(item)">确认</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";

const detections = ref([]);
const alarms = ref([]);
const code = ref("");

async function load() {
  const [items, records] = await Promise.all([
    api.detections(),
    api.alarms(code.value || undefined),
  ]);
  detections.value = items;
  alarms.value = records;
}

async function acknowledge(item) {
  await api.acknowledgeAlarm(item.id);
  await load();
}

onMounted(load);
</script>
