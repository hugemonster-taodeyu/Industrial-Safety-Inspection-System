<template>
  <div>
    <h1 class="page-title">实时监控</h1>
    <div class="live">
      <div>
        <div class="video-wrap">
          <div class="banner" :class="activeAlarm ? 'danger' : 'ok'">
            <span v-if="activeAlarm">
              {{ activeAlarm.title }} · {{ activeAlarm.time }} · {{ activeAlarm.person || "未登记人员" }}
            </span>
            <span v-else>运行正常</span>
            <button v-if="activeAlarm" class="btn banner-ack" type="button" @click="acknowledge(activeAlarm)">确认</button>
          </div>
          <img v-if="cameraOn && !showPicker" ref="videoImg" :src="streamUrl" alt="摄像机画面" @load="layoutZone" />
          <svg
            v-if="drawing && frameBox.width"
            class="zone-svg"
            :style="{ left: frameBox.left + 'px', top: frameBox.top + 'px', width: frameBox.width + 'px', height: frameBox.height + 'px' }"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
            @click="addPoint"
          >
            <polygon v-if="draftPoints.length >= 3" :points="polyPoints" />
            <polyline v-else-if="draftPoints.length" :points="polyPoints" />
            <circle v-for="(point, index) in draftPoints" :key="index" :cx="point[0]" :cy="point[1]" r="0.012" />
          </svg>
          <div v-if="!cameraOn || showPicker" class="video-empty">
            <p>{{ cameraOn ? "更换当前环境的摄像头" : cameraConfigured ? "摄像头未连接" : "未配置摄像头" }}</p>
            <div class="row">
              <select v-model="deviceIndex">
                <option value="">选择本机摄像头</option>
                <option v-for="cam in cameras" :key="cam.index" :value="String(cam.index)">{{ cam.name }}</option>
              </select>
              <button class="btn ghost" type="button" :disabled="connecting || listing" @click="loadCameras">{{ listing ? "刷新中" : "刷新" }}</button>
              <button class="btn" :disabled="deviceIndex === '' || connecting" @click="connectLocal">连接本机</button>
            </div>
            <div class="row">
              <input v-model="streamUrlInput" placeholder="rtsp://账号:密码@IP:554/Streaming/Channels/101" />
              <button class="btn" :disabled="!streamUrlInput.trim() || connecting" @click="connectNetwork">连接网络摄像头</button>
              <button v-if="cameraOn" class="btn ghost" type="button" @click="showPicker = false">取消</button>
            </div>
            <p class="empty">海康主码流一般是上面的地址，子码流把末尾 101 改成 102。摄像头只保存在当前环境。</p>
            <p v-if="camerasLoaded && !cameras.length" class="empty">未发现本机摄像头，仍可填写网络地址连接</p>
            <p v-if="cameraError" class="error">{{ cameraError }}</p>
          </div>
        </div>
        <div class="camera-bar">
          <span class="chip">当前摄像头：{{ cameraLabel }}</span>
          <button class="btn ghost" type="button" @click="showPicker ? closePicker() : openPicker()">
            {{ showPicker ? "取消更换" : "更换摄像头" }}
          </button>
        </div>
      </div>
      <div class="side-stack">
        <aside class="panel">
          <h2>当前检测</h2>
          <div class="panel-body">
            <p v-if="!enabled.length" class="hint">尚未开启检测项</p>
            <section v-if="codeOn(1)" class="ops">
              <h2>人员检测</h2>
              <p class="hint">未登记、黑名单，以及白名单资质过期都会报警。</p>
            </section>
            <section v-if="codeOn(2)" class="ops">
              <h2>二维码工号</h2>
              <p class="hint">二维码内容为 9 位工号。黑名单或资质过期会报警，未登记的工号只显示不报警。</p>
            </section>
            <section v-if="codeOn(3)" class="ops">
              <h2>安全护具</h2>
              <p class="hint">未检测到安全帽时报警。</p>
            </section>
            <section v-if="codeOn(4)" class="ops">
              <h2>危险动作</h2>
              <p class="hint">面向摄像头，把手机贴在耳侧。举手过头不会报警。是否报警按「报警设置」里的累计次数和时间。</p>
            </section>
            <section v-if="codeOn(5)" class="ops">
              <h2>二维码工器具</h2>
              <p class="hint">二维码内容为 6 位器具编号。库里没有，或检定到期日早于今天，都会报警。</p>
            </section>
          </div>
        </aside>
        <aside class="panel">
          <h2>当前报警</h2>
          <div class="panel-body">
            <div v-if="!events.length" class="empty">还没有检测到报警。</div>
            <div v-for="item in events" :key="item.key" class="alarm-item">
              {{ item.title }}
              <div class="meta">{{ item.time }} · {{ item.person }} · {{ item.stage }}</div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: "LiveView" });
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { api } from "../api";

const props = defineProps({
  stage: { type: String, default: "" },
});

const streamToken = ref(0);
const streamUrl = computed(() => `/api/camera/stream?t=${streamToken.value}`);
const detections = ref([]);
const cameras = ref([]);
const camerasLoaded = ref(false);
const cameraConfigured = ref(false);
const cameraName = ref("");
const cameraWidth = ref(0);
const cameraHeight = ref(0);
const deviceIndex = ref("");
const streamUrlInput = ref("");
const showPicker = ref(false);
const connecting = ref(false);
const listing = ref(false);
const cameraError = ref("");
const alarms = ref([]);
const cameraOn = ref(false);
const zonePoints = ref([]);
const draftPoints = ref([]);
const drawing = ref(false);
const savingZone = ref(false);
const zoneError = ref("");
const frameBox = ref({ left: 0, top: 0, width: 0, height: 0 });
const videoImg = ref(null);
const presence = ref({
  active: false,
  remaining: 0,
  operator: false,
  operator_name: "",
  supervisor: false,
  supervisor_name: "",
  result: "",
  detail: "",
});
const checking = ref(false);
const leaveSeconds = ref(30);
const dwellMinutes = ref(10);
const testRunning = ref(false);
const opsError = ref("");
let timer = 0;

const enabled = computed(() => detections.value.filter((item) => item.enabled));
const cameraLabel = computed(() => {
  if (cameraOn.value) return cameraName.value || "已连接";
  return cameraConfigured.value ? "未连接" : "未配置";
});
const events = computed(() =>
  alarms.value
    .filter((item) => !item.simulated)
    .map((item) => ({
      key: `alarm-${item.id}`,
      time: item.time,
      title: item.title,
      person: item.person,
      stage: item.stage,
    }))
);
const activeAlarm = computed(() => alarms.value.find((item) => !item.simulated && !item.acknowledged) || null);
const polyPoints = computed(() => draftPoints.value.map((point) => `${point[0]},${point[1]}`).join(" "));
const presenceText = computed(() => {
  const item = presence.value;
  if (item.active) {
    const operator = item.operator ? item.operator_name : "未到";
    const supervisor = item.supervisor ? item.supervisor_name : "未到";
    return `检查中，剩余 ${item.remaining} 秒。操作人：${operator}；监护人：${supervisor}`;
  }
  if (item.detail) return item.detail;
  return "尚未开始到岗检查";
});

function codeOn(code) {
  return detections.value.some((item) => item.code === code && item.enabled);
}

function layoutZone() {
  const img = videoImg.value;
  if (!img || showPicker.value) {
    frameBox.value = { left: 0, top: 0, width: 0, height: 0 };
    return;
  }
  const naturalWidth = img.naturalWidth || cameraWidth.value;
  const naturalHeight = img.naturalHeight || cameraHeight.value;
  if (!naturalWidth || !naturalHeight) return;
  const boxWidth = img.clientWidth;
  const boxHeight = img.clientHeight;
  const scale = Math.min(boxWidth / naturalWidth, boxHeight / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  frameBox.value = {
    left: img.offsetLeft + (boxWidth - width) / 2,
    top: img.offsetTop + (boxHeight - height) / 2,
    width,
    height,
  };
}

async function refresh() {
  const [items, records, camera, presenceState] = await Promise.all([
    api.detections().catch(() => detections.value),
    api.alarms().catch(() => alarms.value),
    api.cameraStatus().catch(() => null),
    api.presence().catch(() => presence.value),
  ]);
  if (items) detections.value = items;
  if (records) alarms.value = records;
  if (presenceState) presence.value = presenceState;
  if (!camera) return;
  cameraOn.value = camera.connected;
  cameraConfigured.value = camera.configured;
  cameraName.value = camera.device_name || "";
  cameraWidth.value = camera.width || 0;
  cameraHeight.value = camera.height || 0;
  if (camera.source !== "network" && camera.device_index !== null && camera.device_index !== undefined && camera.device_index >= 0 && deviceIndex.value === "") {
    deviceIndex.value = String(camera.device_index);
  }
  if (camera.stream_url && !streamUrlInput.value) streamUrlInput.value = camera.stream_url;
  layoutZone();
}

function closePicker() {
  showPicker.value = false;
  cameraError.value = "";
}

async function loadZone() {
  const zone = await api.zone().catch(() => null);
  if (!zone) return;
  zonePoints.value = zone.points || [];
}

async function loadOps() {
  const settings = await api.settings().catch(() => null);
  if (!settings) return;
  leaveSeconds.value = settings.leave_seconds;
  dwellMinutes.value = settings.dwell_minutes;
  testRunning.value = settings.test_running;
}

async function loadCameras() {
  if (listing.value) return;
  listing.value = true;
  try {
    cameras.value = await api.cameras();
  } catch (err) {
    cameraError.value = err.message;
  }
  camerasLoaded.value = true;
  listing.value = false;
}

async function openPicker() {
  drawing.value = false;
  showPicker.value = true;
  cameraError.value = "";
  await loadCameras();
}

async function applyConnection(payload) {
  cameraError.value = "";
  connecting.value = true;
  try {
    const camera = await api.connectCamera(payload);
    cameraOn.value = camera.connected;
    cameraConfigured.value = camera.configured;
    cameraName.value = camera.device_name || "";
    cameraWidth.value = camera.width || 0;
    cameraHeight.value = camera.height || 0;
    showPicker.value = false;
    streamToken.value += 1;
  } catch (err) {
    cameraError.value = err.message;
  } finally {
    connecting.value = false;
  }
}

function connectLocal() {
  const selected = cameras.value.find((item) => String(item.index) === deviceIndex.value);
  return applyConnection({
    source: "local",
    device_index: Number(deviceIndex.value),
    device_name: selected?.name || "",
  });
}

function connectNetwork() {
  return applyConnection({
    source: "network",
    stream_url: streamUrlInput.value.trim(),
  });
}

function beginDraw() {
  zoneError.value = "";
  if (!cameraOn.value || showPicker.value) {
    zoneError.value = "请先连接摄像头";
    return;
  }
  draftPoints.value = zonePoints.value.map((point) => [...point]);
  drawing.value = true;
  layoutZone();
}

function addPoint(event) {
  if (!drawing.value) return;
  const rect = event.currentTarget.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
  draftPoints.value = [...draftPoints.value, [Number(x.toFixed(4)), Number(y.toFixed(4))]];
}

function undoPoint() {
  draftPoints.value = draftPoints.value.slice(0, -1);
}

function cancelDraw() {
  drawing.value = false;
  draftPoints.value = [];
  zoneError.value = "";
}

async function saveZone() {
  zoneError.value = "";
  savingZone.value = true;
  try {
    const saved = await api.saveZone(draftPoints.value);
    zonePoints.value = saved.points;
    drawing.value = false;
    draftPoints.value = [];
  } catch (err) {
    zoneError.value = err.message;
  } finally {
    savingZone.value = false;
  }
}

async function clearZone() {
  zoneError.value = "";
  try {
    const saved = await api.deleteZone();
    zonePoints.value = saved.points;
    draftPoints.value = [];
    drawing.value = false;
  } catch (err) {
    zoneError.value = err.message;
  }
}

async function startPresence() {
  opsError.value = "";
  checking.value = true;
  try {
    presence.value = await api.startPresence();
  } catch (err) {
    opsError.value = err.message;
  } finally {
    checking.value = false;
  }
}

async function saveDurations() {
  opsError.value = "";
  try {
    const settings = await api.updateSettings({
      leave_seconds: leaveSeconds.value,
      dwell_minutes: dwellMinutes.value,
    });
    leaveSeconds.value = settings.leave_seconds;
    dwellMinutes.value = settings.dwell_minutes;
    testRunning.value = settings.test_running;
  } catch (err) {
    opsError.value = err.message;
  }
}

async function toggleTest() {
  opsError.value = "";
  try {
    const settings = await api.updateSettings({
      test_running: !testRunning.value,
      leave_seconds: leaveSeconds.value,
      dwell_minutes: dwellMinutes.value,
    });
    leaveSeconds.value = settings.leave_seconds;
    dwellMinutes.value = settings.dwell_minutes;
    testRunning.value = settings.test_running;
  } catch (err) {
    opsError.value = err.message;
  }
}

async function acknowledge(alarm) {
  await api.acknowledgeAlarm(alarm.id);
  await refresh();
}

watch(
  () => props.stage,
  async () => {
    showPicker.value = false;
    deviceIndex.value = "";
    drawing.value = false;
    draftPoints.value = [];
    await refresh();
    await loadZone();
    await loadOps();
  }
);

function onResize() {
  layoutZone();
}

onMounted(async () => {
  await refresh();
  await loadZone();
  await loadOps();
  window.addEventListener("resize", onResize);
  timer = window.setInterval(refresh, 2000);
});

onUnmounted(() => {
  window.clearInterval(timer);
  window.removeEventListener("resize", onResize);
});
</script>
