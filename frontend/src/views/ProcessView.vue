<template>
  <div>
    <h1 class="page-title">流程检测</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="live">
      <div>
        <div class="process-stage">
          <video v-if="videoUrl" ref="videoEl" :class="{ 'hidden-decoder': stillUrl }" :src="videoUrl" controls @loadedmetadata="onMeta" @timeupdate="onTime"></video>
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
import { nextTick, onUnmounted, ref } from "vue";
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
const time = ref(0);
const duration = ref(0);
const slider = ref(0);
let stillObjectUrl = "";
let scrubbing = false;
let pendingSeek = null;
let processFinished = false;

function blankSteps() {
  return [
    { name: "启动", passed: false },
    { name: "检查变压器", passed: false, sides: { front: false, back: false, left: false, right: false } },
    { name: "接线", passed: false, parts: { connect_terminal_a: false, connect_terminal_b: false, connect_terminal_c: false, connect_ground_terminal: false } },
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
  if (!video || scrubbing || running.value) return;
  time.value = video.currentTime;
  if (video.duration) slider.value = Math.round((video.currentTime / video.duration) * 1000);
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
  if (running.value) {
    pendingSeek = target;
    return;
  }
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
  boxes.value = status.boxes || [];
  if (status.current >= status.steps.length) {
    running.value = false;
    processFinished = true;
  }
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
  time.value = 0;
  duration.value = 0;
  slider.value = 0;
  pendingSeek = null;
  processFinished = false;
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
  time.value = 0;
  duration.value = 0;
  slider.value = 0;
  pendingSeek = null;
  processFinished = false;
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

async function playRest(video) {
  clearStill();
  boxes.value = [];
  await nextTick();
  if (video.currentTime >= video.duration - 0.05) return;
  try {
    await video.play();
  } catch {
    // 浏览器拦截自动播放时，画面已经回到视频，可以用控件继续播放。
  }
}

async function runFrames() {
  const video = videoEl.value;
  processFinished = false;
  while (running.value && video) {
    if (pendingSeek != null) {
      const target = pendingSeek;
      pendingSeek = null;
      await seek(video, Math.min(Math.max(target, 0), Math.max(video.duration - 0.001, 0)));
    }
    if (!running.value) break;
    if (video.currentTime >= video.duration - 0.001) {
      stopLoop();
      break;
    }
    const blob = await capture(video);
    if (!blob || !running.value) break;
    if (pendingSeek != null) continue;
    let status;
    try {
      status = await api.processFrame(blob, video.currentTime);
    } catch (err) {
      error.value = err.message;
      stopLoop();
      break;
    }
    if (!running.value || pendingSeek != null) continue;
    showStill(blob);
    applyStatus(status);
    if (!scrubbing && video.duration) {
      time.value = video.currentTime;
      slider.value = Math.round((video.currentTime / video.duration) * 1000);
    }
    if (!running.value || pendingSeek != null) continue;
    const next = Math.min(video.duration, video.currentTime + 10 / 25);
    if (next >= video.duration - 0.001) {
      stopLoop();
      break;
    }
    await seek(video, next);
  }
  if (processFinished && video) await playRest(video);
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
