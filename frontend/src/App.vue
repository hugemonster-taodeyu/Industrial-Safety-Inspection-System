<template>
  <div class="app">
    <aside class="side">
      <div class="brand">工程行为安全检测系统</div>
      <router-link class="nav-link" to="/">实时监控</router-link>
      <router-link class="nav-link" to="/detections">检测项配置</router-link>
      <router-link class="nav-link" to="/people">人员名单</router-link>
      <router-link class="nav-link" to="/tools">工器具</router-link>
      <router-link class="nav-link" to="/alarms">报警记录</router-link>
    </aside>
    <section class="main">
      <header class="top">
        <label>
          摄像机
          <span class="cam-dot" :class="{ on: cameraOn }"></span>
          {{ cameraLabel }}
        </label>
        <label>
          当前环境
          <select :value="String(stage)" @change="onStage">
            <option v-for="item in stages" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
          </select>
          <button class="btn ghost" type="button" @click="renameEnvironment">改名</button>
          <button class="btn ghost" type="button" @click="addEnvironment">新增</button>
          <button class="btn danger" type="button" @click="deleteEnvironment">删除</button>
        </label>
        <span v-if="envError" class="error">{{ envError }}</span>
        <label class="sound">
          <input type="checkbox" :checked="soundEnabled" @change="onSound" />
          声音报警
        </label>
      </header>
      <div class="content">
        <router-view v-slot="{ Component }">
          <keep-alive include="LiveView">
            <component :is="Component" :stage="stage" />
          </keep-alive>
        </router-view>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "./api";

const stage = ref("");
const stages = ref([]);
const envError = ref("");
const cameraOn = ref(false);
const cameraConfigured = ref(false);
const cameraName = ref("");
const soundEnabled = ref(false);
let timer = 0;
let seenAlarmId = 0;
let alarmBaseline = false;
let audioCtx = null;

const cameraLabel = computed(() => {
  if (cameraOn.value) return cameraName.value || "已连接";
  return cameraConfigured.value ? "未连接" : "未配置";
});

function applyCamera(camera) {
  cameraOn.value = camera.connected;
  cameraConfigured.value = camera.configured;
  cameraName.value = camera.device_name || "";
}

async function load() {
  const [settings, stageData, camera] = await Promise.all([
    api.settings(),
    api.stages(),
    api.cameraStatus(),
  ]);
  stage.value = String(settings.stage || "");
  stages.value = stageData.stages;
  soundEnabled.value = settings.sound_enabled;
  applyCamera(camera);
}

function primeAudio() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  if (!audioCtx) audioCtx = new Ctx();
  if (audioCtx.state === "suspended") audioCtx.resume();
}

function beep() {
  primeAudio();
  if (!audioCtx) return;
  const now = audioCtx.currentTime;
  for (const offset of [0, 0.18]) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, now + offset);
    gain.gain.exponentialRampToValueAtTime(0.15, now + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.16);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.17);
  }
}

async function onSound(event) {
  const enabled = event.target.checked;
  primeAudio();
  try {
    const next = await api.updateSettings({ sound_enabled: enabled });
    soundEnabled.value = next.sound_enabled;
  } catch {
    event.target.checked = soundEnabled.value;
  }
}

async function pollAlarms() {
  const records = await api.alarms().catch(() => null);
  if (!records) return;
  const maxId = records.reduce((max, item) => (!item.simulated && item.id > max ? item.id : max), 0);
  if (alarmBaseline && soundEnabled.value && maxId > seenAlarmId) beep();
  seenAlarmId = Math.max(seenAlarmId, maxId);
  alarmBaseline = true;
}

async function onStage(event) {
  envError.value = "";
  try {
    const next = await api.setStage(event.target.value);
    stage.value = String(next.stage);
    applyCamera(await api.cameraStatus());
  } catch (err) {
    envError.value = err.message;
  }
}

async function renameEnvironment() {
  const current = stages.value.find((item) => String(item.id) === String(stage.value));
  if (!current) return;
  const name = window.prompt("环境名称", current.name);
  if (name === null) return;
  envError.value = "";
  try {
    await api.renameEnvironment(current.id, name.trim());
    stages.value = (await api.stages()).stages;
  } catch (err) {
    envError.value = err.message;
  }
}

async function deleteEnvironment() {
  const current = stages.value.find((item) => String(item.id) === String(stage.value));
  if (!current) return;
  if (stages.value.length < 2) {
    envError.value = "至少保留一个环境";
    return;
  }
  const confirmed = window.confirm(`确定删除「${current.name}」？该环境的检测开关和摄像头会一并删除。`);
  if (!confirmed) return;
  envError.value = "";
  try {
    const result = await api.deleteEnvironment(current.id);
    stages.value = (await api.stages()).stages;
    stage.value = String(result.stage);
    applyCamera(await api.cameraStatus());
  } catch (err) {
    envError.value = err.message;
  }
}

async function addEnvironment() {
  const name = window.prompt("新环境名称", `环境${stages.value.length + 1}`);
  if (name === null) return;
  envError.value = "";
  try {
    const created = await api.createEnvironment(name.trim());
    stages.value = (await api.stages()).stages;
    stage.value = String(created.stage);
    applyCamera(await api.cameraStatus());
  } catch (err) {
    envError.value = err.message;
  }
}

onMounted(() => {
  load();
  pollAlarms();
  window.addEventListener("pointerdown", primeAudio, { once: true });
  timer = window.setInterval(async () => {
    applyCamera(await api.cameraStatus());
    pollAlarms();
  }, 2000);
});

onUnmounted(() => window.clearInterval(timer));
</script>
