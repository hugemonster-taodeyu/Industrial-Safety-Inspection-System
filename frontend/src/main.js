import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import LiveView from "./views/LiveView.vue";
import DetectionsView from "./views/DetectionsView.vue";
import PeopleView from "./views/PeopleView.vue";
import ToolsView from "./views/ToolsView.vue";
import AlarmsView from "./views/AlarmsView.vue";
import AlarmSettingsView from "./views/AlarmSettingsView.vue";
import "./styles.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: LiveView },
    { path: "/detections", component: DetectionsView },
    { path: "/people", component: PeopleView },
    { path: "/tools", component: ToolsView },
    { path: "/alarm-settings", component: AlarmSettingsView },
    { path: "/alarms", component: AlarmsView },
  ],
});

createApp(App).use(router).mount("#app");
