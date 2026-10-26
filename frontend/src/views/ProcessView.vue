<template>
  <div>
    <h1 class="page-title">流程检测</h1>
    <div class="note">选择本地视频后点击「开始」。每一帧检测完才显示这一帧和它的框，然后再检测下一帧。四个步骤按顺序进行。</div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="live">
      <div>
        <div class="process-stage">
          <video v-if="videoUrl" ref="videoEl" :class="{ 'hidden-decoder': stillUrl }" :src="videoUrl" controls></video>
          <img v-if="stillUrl" class="process-frame" :src="stillUrl" alt="" />
          <svg v-if="stillUrl && boxes.length" class="process-overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
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
          <button class="btn" type="button" :disabled="!videoUrl || running" @click="start">{{ running ? "检测中" : "开始" }}</button>
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
import { onUnmounted, ref } from "vue";
import { api } from "../api";

const steps = ref(blankSteps());
const current = ref(0);
const boxes = ref([]);
const videoUrl = ref("");
const fileName = ref("");
const videoEl = ref(null);
const stillUrl = ref("");
const running = ref(false);
const error = ref("");
let stillObjectUrl = "";

function blankSteps() {
  return [
    { name: "启动", passed: false },
    { name: "检查变压器", passed: false, sides: { front: false, back: false, left: false, right: false } },
    { name: "接线", passed: false, parts: { connect_terminal_a: false, connect_terminal_b: false, connect_terminal_c: false, connect_ground_terminal: false } },
    { name: "放电", passed: false },
  ];
}

function stateText(step, index) {
  if (step.passed) return "通过";
  if (running.value && index === current.value) return "检测中";
  return "待检测";
}

function applyStatus(status) {
  steps.value = status.steps;
  current.value = status.current;
  boxes.value = status.boxes || [];
  if (status.current >= status.steps.length) running.value = false;
}

function clearStill() {
  if (stillObjectUrl) URL.revokeObjectURL(stillObjectUrl);
  stillObjectUrl = "";
  stillUrl.value = "";
}

function showStill(blob) {
  const next = URL.createObjectURL(blob);
  if (stillObjectUrl) URL.revokeObjectURL(stillObjectUrl);
  stillObjectUrl = next;
  stillUrl.value = next;
}

function onFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  stopLoop();
  clearStill();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
  videoUrl.value = URL.createObjectURL(file);
  fileName.value = file.name;
  steps.value = blankSteps();
  current.value = 0;
  boxes.value = [];
  error.value = "";
}

function clearVideo() {
  stopLoop();
  clearStill();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
  videoUrl.value = "";
  fileName.value = "";
  steps.value = blankSteps();
  boxes.value = [];
}

function seek(video, time) {
  return new Promise((resolve) => {
    if (Math.abs(video.currentTime - time) < 0.001) {
      resolve();
      return;
    }
    const done = () => {
      video.removeEventListener("seeked", done);
      resolve();
    };
    video.addEventListener("seeked", done);
    video.currentTime = time;
  });
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
  try {
    applyStatus(await api.startProcess());
  } catch (err) {
    error.value = err.message;
    return;
  }
  if (video.readyState < 2) {
    await new Promise((resolve) => video.addEventListener("loadeddata", resolve, { once: true }));
  }
  video.pause();
  running.value = true;
  await runFrames();
}

async function runFrames() {
  const video = videoEl.value;
  while (running.value && video) {
    if (video.currentTime >= video.duration - 0.001) {
      stopLoop();
      break;
    }
    const blob = await capture(video);
    if (!blob || !running.value) break;
    let status;
    try {
      status = await api.processFrame(blob);
    } catch (err) {
      error.value = err.message;
      stopLoop();
      break;
    }
    if (!running.value) break;
    showStill(blob);
    applyStatus(status);
    if (!running.value) break;
    const next = Math.min(video.duration, video.currentTime + 1 / 25);
    if (next >= video.duration - 0.001) {
      stopLoop();
      break;
    }
    await seek(video, next);
  }
}

function stopLoop() {
  running.value = false;
}

onUnmounted(() => {
  stopLoop();
  clearStill();
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
});
</script>
