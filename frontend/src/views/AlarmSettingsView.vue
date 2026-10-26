<template>
  <div>
    <h1 class="page-title">报警设置</h1>
    <div class="note">五项检测共用下面三个参数。在累计时间内达到累计次数后才写入报警，同一对象在报警间隔内不会再次报警。</div>
    <form class="settings-form" @submit.prevent="save">
      <label class="field">累计时间（秒）
        <input v-model.number="form.alarm_window_seconds" type="number" min="1" max="120" required />
      </label>
      <label class="field">累计次数
        <input v-model.number="form.alarm_count" type="number" min="1" max="20" required />
      </label>
      <label class="field">报警间隔（秒）
        <input v-model.number="form.alarm_gap_seconds" type="number" min="1" max="600" required />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="saved" class="hint">已保存</p>
      <button class="btn" type="submit" :disabled="saving">保存</button>
    </form>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";

const form = ref({
  alarm_window_seconds: 3,
  alarm_count: 3,
  alarm_gap_seconds: 20,
});
const error = ref("");
const saved = ref(false);
const saving = ref(false);

async function load() {
  error.value = "";
  const settings = await api.settings();
  form.value = {
    alarm_window_seconds: settings.alarm_window_seconds,
    alarm_count: settings.alarm_count,
    alarm_gap_seconds: settings.alarm_gap_seconds,
  };
}

async function save() {
  error.value = "";
  saved.value = false;
  saving.value = true;
  try {
    const next = await api.updateSettings({
      alarm_window_seconds: form.value.alarm_window_seconds,
      alarm_count: form.value.alarm_count,
      alarm_gap_seconds: form.value.alarm_gap_seconds,
    });
    form.value = {
      alarm_window_seconds: next.alarm_window_seconds,
      alarm_count: next.alarm_count,
      alarm_gap_seconds: next.alarm_gap_seconds,
    };
    saved.value = true;
  } catch (err) {
    error.value = err.message;
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
