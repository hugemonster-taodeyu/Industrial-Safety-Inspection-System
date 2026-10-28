<template>
  <div>
    <h1 class="page-title">流程检测</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="live">
      <div>
        <div class="process-stage">
          <video v-if="videoUrl" ref="videoEl" :src="videoUrl" controls @loadedmetadata="onMeta" @timeupdate="onTime" @seeked="onSeeked" @ended="onEnded"></video>
          <svg v-if="boxes.length" class="process-overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
            <rect
              v-for="(box, index) in boxes"
              :key="index"
              :x="box.x1"
              :y="box.y1"
              :width="Math.max(box.x2 - box.x1, 0)"
              :height="Math.max(box.y2 - box.y1, 0)"
            />
          </svg>
          <div v-if="!videoUrl" class="video-wrap">
            <div class="video-empty">
              <p>还没有选择视频</p>
            </div>
          </div>
        </div>
        <div class="camera-bar">
          <span class="time">{{ clock(time) }}</span>
          <input
            class="progress"
            type="range"
            min="0"
            max="1000"
            :value="slider"
            :disabled="!videoUrl"
            @pointerdown="scrubbing = true"
            @input="onSliderInput"
            @change="onSliderChange"
          />
          <span class="time">{{ clock(duration) }}</span>
        </div>
        <div class="camera-bar">
          <span class="chip">{{ fileName || "未选择视频" }}</span>
          <div class="row">
            <label class="btn">
              选择视频
              <input class="file-input" type="file" accept="video/*" @change="onFile" />
            </label>
            <button v-if="videoUrl" class="btn ghost" type="button" @click="clearVideo">清除</button>
          </div>
        </div>
      </div>
      <aside class="panel process-panel">
        <div class="process-head">
          <h2>检测流程</h2>
        </div>
        <ol class="steps">
          <li v-for="(step, index) in steps" :key="step.name" class="step" :class="{ passed: step.passed, current: running && index === current }">
            <span class="step-index">{{ index + 1 }}</span>
            <span class="step-body">
              <span class="step-name">{{ step.name }}</span>
              <span v-if="step.sides" class="side-row">
                <span :class="{ on: step.sides.front }">前</span>
                <span :class="{ on: step.sides.back }">后</span>
                <span :class="{ on: step.sides.left }">左</span>
                <span :class="{ on: step.sides.right }">右</span>
              </span>
              <span v-if="step.parts" class="side-row">
                <span :class="{ on: step.parts.connect_terminal_a }">A</span>
                <span :class="{ on: step.parts.connect_terminal_b }">B</span>
                <span :class="{ on: step.parts.connect_terminal_c }">C</span>
                <span :class="{ on: step.parts.connect_ground_terminal }">地线</span>
              </span>
            </span>
            <span class="step-state">{{ stateText(step, index) }}</span>
          </li>
        </ol>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onUnmounted, ref } from "vue";
import { api } from "../api";

const steps = ref(blankSteps());
const current = ref(0);
const boxes = ref([]);
const videoUrl = ref("");
const fileName = ref("");
const videoEl = ref(null);
const running = ref(false);
const error = ref("");
const time = ref(0);
const duration = ref(0);
const slider = ref(0);
const sampleGap = 0.1;
let scrubbing = false;
let sampleTimer = null;
let sampleGeneration = 0;
let sending = false;
let lastSampleTime = -1;

function blankSteps() {
  return [
    { name: "启动", passed: false },
    { name: "检查变压器", passed: false, sides: { front: false, back: false, left: false, right: false } },
    { name: "接线", passed: false, parts: { connect_terminal_a: false, connect_terminal_b: false, connect_terminal_c: false, connect_ground_terminal: false } },
    { name: "结束", passed: false, parts: { connect_terminal_a: false, connect_terminal_b: false, connect_terminal_c: false, connect_ground_terminal: false } },
  ];
}

function clock(seconds) {
  const value = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(value / 60);
  const remain = value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

function onMeta() {
  const video = videoEl.value;
  if (!video) return;
  duration.value = video.duration || 0;
}

function onTime() {
  const video = videoEl.value;
  if (!video || scrubbing) return;
  time.value = video.currentTime;
  if (video.duration) slider.value = Math.round((video.currentTime / video.duration) * 1000);
}

function onEnded() {
  if (running.value) stopLoop();
}

function onSeeked() {
  if (!running.value) return;
  boxes.value = [];
  lastSampleTime = -1;
}

function onSliderInput(event) {
  scrubbing = true;
  slider.value = Number(event.target.value);
  if (duration.value) time.value = (slider.value / 1000) * duration.value;
}

function onSliderChange(event) {
  const video = videoEl.value;
  scrubbing = false;
  slider.value = Number(event.target.value);
  if (!video?.duration) return;
  const target = (slider.value / 1000) * video.duration;
  time.value = target;
  if (running.value) boxes.value = [];
  video.currentTime = target;
}

function stateText(step, index) {
  if (step.passed) return "通过";
  if (running.value && index === current.value) return "检测中";
  return "待检测";
}

function applyStatus(status) {
  steps.value = status.steps;
  current.value = status.current;
  const finished = status.current >= status.steps.length;
  boxes.value = finished ? [] : status.boxes || [];
  if (finished) stopLoop();
}

async function onFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  stopLoop();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
  videoUrl.value = URL.createObjectURL(file);
  fileName.value = file.name;
  steps.value = blankSteps();
  current.value = 0;
  boxes.value = [];
  time.value = 0;
  duration.value = 0;
  slider.value = 0;
  error.value = "";
  await nextTick();
  await start();
}

function clearVideo() {
  stopLoop();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
  videoUrl.value = "";
  fileName.value = "";
  steps.value = blankSteps();
  boxes.value = [];
  time.value = 0;
  duration.value = 0;
  slider.value = 0;
}

function capture(video) {
  const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
}

async function start() {
  const video = videoEl.value;
  if (!video) return;
  error.value = "";
  boxes.value = [];
  if (video.readyState < 2) {
    await new Promise((resolve) => video.addEventListener("loadeddata", resolve, { once: true }));
  }
  try {
    await video.play();
  } catch (err) {
    error.value = err.message || "无法播放视频";
    return;
  }
  running.value = true;
  lastSampleTime = -1;
  try {
    applyStatus(await api.startProcess());
  } catch (err) {
    video.pause();
    stopLoop();
    error.value = err.message;
    return;
  }
  beginSampling(video);
}

function beginSampling(video) {
  stopSampling();
  const generation = sampleGeneration;
  sampleTimer = setInterval(() => {
    sampleFrame(video, generation);
  }, 30);
}

function stopSampling() {
  sampleGeneration += 1;
  sending = false;
  if (sampleTimer) {
    clearInterval(sampleTimer);
    sampleTimer = null;
  }
}

async function sampleFrame(video, generation) {
  if (generation !== sampleGeneration || !running.value || sending) return;
  if (video.ended) {
    stopLoop();
    return;
  }
  if (video.paused) return;
  const now = video.currentTime;
  const delta = now - lastSampleTime;
  if (lastSampleTime >= 0 && delta >= -0.05 && delta < sampleGap) return;
  lastSampleTime = now;
  sending = true;
  try {
    const blob = await capture(video);
    if (generation !== sampleGeneration || !running.value || !blob) return;
    const status = await api.processFrame(blob, now);
    if (generation !== sampleGeneration || !running.value) return;
    if (Math.abs(video.currentTime - now) > 1.5) {
      boxes.value = [];
      return;
    }
    applyStatus(status);
  } catch (err) {
    if (generation !== sampleGeneration || !running.value) return;
    error.value = err.message;
    stopLoop();
  } finally {
    if (generation === sampleGeneration) sending = false;
  }
}

function stopLoop() {
  running.value = false;
  stopSampling();
}

onUnmounted(() => {
  stopLoop();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
});
</script>
