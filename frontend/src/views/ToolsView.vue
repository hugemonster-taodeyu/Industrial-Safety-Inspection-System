<template>
  <div>
    <h1 class="page-title">工器具</h1>
    <div class="note">
      编号为 6 位数字，也是二维码内容。当前环境开启「二维码工器具检测」后，未录入或检定到期都会报警。
    </div>
    <div class="tabs">
      <button class="btn ghost" @click="openCreate">新增</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <table>
      <thead>
        <tr>
          <th>编号</th><th>名称</th><th>检定到期</th><th>启用</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!tools.length">
          <td colspan="5" class="empty">暂无工器具</td>
        </tr>
        <tr v-for="item in tools" :key="item.id">
          <td>{{ item.tool_no || "—" }}</td>
          <td>{{ item.name }}</td>
          <td>{{ item.calibration_expiry || "—" }}</td>
          <td>{{ item.enabled ? "是" : "否" }}</td>
          <td class="row">
            <button class="btn ghost" type="button" @click="openEdit(item)">编辑</button>
            <button class="btn danger" type="button" @click="remove(item)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="editing" class="modal-mask" @click.self="editing = null">
      <form class="modal" @submit.prevent="save">
        <h2>{{ form.id ? "编辑工器具" : "新增工器具" }}</h2>
        <label class="field">编号（6 位数字）<input v-model="form.tool_no" inputmode="numeric" maxlength="6" placeholder="例如 100001" required /></label>
        <label class="field">名称<input v-model="form.name" required /></label>
        <label class="field">检定到期日<input v-model="form.calibration_expiry" type="date" /></label>
        <label class="field"><span class="row"><input v-model="form.enabled" type="checkbox" /> 启用</span></label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="row">
          <button class="btn" type="submit">保存</button>
          <button class="btn ghost" type="button" @click="editing = null">取消</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";

const tools = ref([]);
const error = ref("");
const formError = ref("");
const editing = ref(null);
const form = ref(blank());

function blank() {
  return { id: null, tool_no: "", name: "", calibration_expiry: "", qr_text: "", enabled: true };
}

async function load() {
  error.value = "";
  tools.value = await api.tools();
}

function openCreate() {
  form.value = blank();
  formError.value = "";
  editing.value = true;
}

function openEdit(item) {
  form.value = {
    id: item.id,
    tool_no: item.tool_no,
    name: item.name,
    calibration_expiry: item.calibration_expiry,
    qr_text: item.qr_text,
    enabled: item.enabled,
  };
  formError.value = "";
  editing.value = true;
}

async function save() {
  formError.value = "";
  try {
    await api.saveTool(
      {
        tool_no: form.value.tool_no,
        name: form.value.name,
        calibration_expiry: form.value.calibration_expiry,
        qr_text: form.value.qr_text,
        enabled: form.value.enabled,
      },
      form.value.id
    );
    editing.value = null;
    await load();
  } catch (err) {
    formError.value = err.message;
  }
}

async function remove(item) {
  if (!window.confirm(`删除 ${item.name}？`)) return;
  await api.deleteTool(item.id);
  await load();
}

onMounted(load);
</script>
