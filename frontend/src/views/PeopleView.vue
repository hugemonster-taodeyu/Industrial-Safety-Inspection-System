<template>
  <div>
    <h1 class="page-title">人员名单</h1>
    <div class="note">
      人脸照片在「人员检测」开启后参与比对。工号填写 9 位数字，供「二维码工号检测」使用：黑名单或资质过期会报警。
    </div>
    <div class="tabs">
      <button class="btn" :class="{ ghost: tab !== 'white' }" @click="tab = 'white'">白名单</button>
      <button class="btn" :class="{ ghost: tab !== 'black' }" @click="tab = 'black'">黑名单</button>
      <button class="btn ghost" @click="openCreate">新增</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <table>
      <thead>
        <tr v-if="tab === 'white'">
          <th>照片</th><th>姓名</th><th>工号</th><th>角色</th><th>资质到期</th><th>电子工牌</th><th>启用</th><th></th>
        </tr>
        <tr v-else>
          <th>照片</th><th>姓名</th><th>标识</th><th>拉黑原因</th><th>启用</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!people.length">
          <td :colspan="tab === 'white' ? 8 : 6" class="empty">暂无人员</td>
        </tr>
        <tr v-for="person in people" :key="person.id">
          <td><img v-if="person.photo_url" class="face" :src="person.photo_url" alt="" /><span v-else class="empty">无</span></td>
          <td>{{ person.name }}</td>
          <td>{{ person.employee_no || "—" }}</td>
          <template v-if="tab === 'white'">
            <td>{{ person.role === "supervisor" ? "监护人" : "操作人" }}</td>
            <td>{{ person.qualification_expiry || "—" }}</td>
            <td>{{ person.badge_no || "—" }}</td>
          </template>
          <template v-else>
            <td>{{ person.reason || "—" }}</td>
          </template>
          <td>{{ person.enabled ? "是" : "否" }}</td>
          <td class="row">
            <button class="btn ghost" @click="openEdit(person)">编辑</button>
            <button class="btn danger" @click="remove(person)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="editing" class="modal-mask" @click.self="editing = null">
      <form class="modal" @submit.prevent="save">
        <h2>{{ form.id ? "编辑人员" : "新增人员" }}</h2>
        <label class="field">姓名<input v-model="form.name" required /></label>
        <label class="field">工号（9 位数字）<input v-model="form.employee_no" inputmode="numeric" maxlength="9" placeholder="例如 100000001" /></label>
        <label v-if="tab === 'white'" class="field">角色
          <select v-model="form.role">
            <option value="operator">操作人</option>
            <option value="supervisor">监护人</option>
          </select>
        </label>
        <label v-if="tab === 'white'" class="field">资质到期日<input v-model="form.qualification_expiry" type="date" /></label>
        <label v-if="tab === 'white'" class="field">电子工牌号<input v-model="form.badge_no" /></label>
        <label v-if="tab === 'black'" class="field">拉黑原因<textarea v-model="form.reason" rows="3"></textarea></label>
        <label class="field">人脸照片<input type="file" accept="image/jpeg,image/png,image/webp" @change="onFile" /></label>
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
import { onMounted, ref, watch } from "vue";
import { api } from "../api";

const tab = ref("white");
const people = ref([]);
const error = ref("");
const formError = ref("");
const editing = ref(null);
const form = ref(blank());
const photo = ref(null);

function blank() {
  return {
    id: null,
    name: "",
    employee_no: "",
    role: "operator",
    qualification_expiry: "",
    badge_no: "",
    reason: "",
    enabled: true,
  };
}

async function load() {
  error.value = "";
  people.value = await api.people(tab.value);
}

function openCreate() {
  form.value = blank();
  photo.value = null;
  formError.value = "";
  editing.value = true;
}

function openEdit(person) {
  form.value = {
    id: person.id,
    name: person.name,
    employee_no: person.employee_no,
    role: person.role || "operator",
    qualification_expiry: person.qualification_expiry,
    badge_no: person.badge_no,
    reason: person.reason,
    enabled: person.enabled,
  };
  photo.value = null;
  formError.value = "";
  editing.value = true;
}

function onFile(event) {
  photo.value = event.target.files?.[0] || null;
}

async function save() {
  formError.value = "";
  try {
    const saved = await api.savePerson(
      {
        list_type: tab.value,
        name: form.value.name,
        employee_no: form.value.employee_no,
        role: form.value.role,
        qualification_expiry: form.value.qualification_expiry,
        badge_no: form.value.badge_no,
        reason: form.value.reason,
        enabled: form.value.enabled,
      },
      form.value.id
    );
    if (photo.value) await api.uploadPhoto(saved.id, photo.value);
    editing.value = null;
    await load();
  } catch (err) {
    formError.value = err.message;
  }
}

async function remove(person) {
  if (!window.confirm(`删除 ${person.name}？`)) return;
  await api.deletePerson(person.id);
  await load();
}

watch(tab, load);
onMounted(load);
</script>
