async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("后端没有响应，请先启动后端");
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!response.ok) throw new Error("后端没有响应，请先启动后端");
      throw new Error("返回内容无法读取");
    }
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg).filter(Boolean).join("；")
        : "";
    throw new Error(message || "请求失败");
  }
  return data;
}

export const api = {
  settings: () => request("/api/settings"),
  stages: () => request("/api/stages"),
  createEnvironment: (name) =>
    request("/api/environments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  renameEnvironment: (id, name) =>
    request(`/api/environments/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  deleteEnvironment: (id) => request(`/api/environments/${id}`, { method: "DELETE" }),
  setStage: (stage) =>
    request("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    }),
  updateSettings: (payload) =>
    request("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  startProcess: () => request("/api/process/start", { method: "POST" }),
  processFrame: (blob, time) => {
    const body = new FormData();
    body.append("file", blob, "frame.jpg");
    body.append("time", String(time));
    return request("/api/process/frame", { method: "POST", body });
  },
  detections: () => request("/api/detections"),
  toggleDetection: (code, enabled) =>
    request(`/api/detections/${code}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  bulkToggle: (category, enabled) =>
    request("/api/detections/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, enabled }),
    }),
  people: (listType) => request(listType ? `/api/people?list_type=${listType}` : "/api/people"),
  savePerson: (payload, id) =>
    request(id ? `/api/people/${id}` : "/api/people", {
      method: id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deletePerson: (id) => request(`/api/people/${id}`, { method: "DELETE" }),
  uploadPhoto: (id, file) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/api/people/${id}/photo`, { method: "POST", body });
  },
  alarms: (code) => request(code ? `/api/alarms?code=${code}` : "/api/alarms"),
  acknowledgeAlarm: (id) =>
    request(`/api/alarms/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledged: true }),
    }),
  zone: () => request("/api/zone"),
  saveZone: (points) =>
    request("/api/zone", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points }),
    }),
  deleteZone: () => request("/api/zone", { method: "DELETE" }),
  presence: () => request("/api/presence"),
  startPresence: () => request("/api/presence/start", { method: "POST" }),
  tools: () => request("/api/tools"),
  saveTool: (payload, id) =>
    request(id ? `/api/tools/${id}` : "/api/tools", {
      method: id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTool: (id) => request(`/api/tools/${id}`, { method: "DELETE" }),
  simulatePresence: (personId) =>
    request("/api/alarms/simulate-presence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ person_id: personId }),
    }),
  cameraStatus: () => request("/api/camera/status"),
  cameras: () => request("/api/cameras"),
  connectCamera: (payload) =>
    request("/api/camera/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};
