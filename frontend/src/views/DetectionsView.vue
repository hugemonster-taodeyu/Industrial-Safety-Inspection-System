<template>
  <div>
    <h1 class="page-title">检测项配置</h1>
    <div class="note">下面五项只对当前环境生效。换一个环境后，可以单独选择要开启的检测和摄像头。</div>
    <section class="group">
      <div class="group-head">
        <h2>检测项</h2>
        <div class="row">
          <button class="btn" @click="setAll(true)">全部开启</button>
          <button class="btn ghost" @click="setAll(false)">全部关闭</button>
        </div>
      </div>
      <div class="cards">
        <article v-for="item in items" :key="item.code" class="card">
          <h3>{{ item.code }}. {{ item.title }}</h3>
          <label class="switch">
            <input type="checkbox" :checked="item.enabled" @change="toggle(item, $event)" />
            <span class="slider"></span>
          </label>
          <p>{{ item.method }}</p>
        </article>
      </div>
    </section>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { api } from "../api";

const props = defineProps({
  stage: { type: String, default: "" },
});

const items = ref([]);
const error = ref("");

async function load() {
  items.value = await api.detections();
}

async function toggle(item, event) {
  error.value = "";
  const enabled = event.target.checked;
  try {
    const updated = await api.toggleDetection(item.code, enabled);
    item.enabled = updated.enabled;
  } catch (err) {
    event.target.checked = item.enabled;
    error.value = err.message;
  }
}

async function setAll(enabled) {
  error.value = "";
  try {
    items.value = await api.bulkToggle("check", enabled);
  } catch (err) {
    error.value = err.message;
  }
}

watch(() => props.stage, load);
onMounted(load);
</script>
