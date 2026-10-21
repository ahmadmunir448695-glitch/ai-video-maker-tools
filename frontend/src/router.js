import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import DashboardView from "@/views/DashboardView.vue";

const routes = [
  {
    path: "/sign-in",
    name: "sign-in",
    component: () => import("@/views/AuthView.vue"),
    meta: { guest: true, title: "Sign in" },
  },
  { path: "/", name: "dashboard", component: DashboardView, meta: { title: "Dashboard" } },
  {
    path: "/upload",
    name: "upload",
    component: () => import("@/views/UploadView.vue"),
    meta: { title: "Upload a video" },
  },
  {
    path: "/videos",
    name: "videos",
    component: () => import("@/views/VideosView.vue"),
    meta: { title: "Your videos" },
  },
  {
    path: "/editor/:id",
    name: "editor",
    component: () => import("@/views/EditorView.vue"),
    props: true,
    meta: { title: "Editor" },
  },
  {
    path: "/exports",
    name: "exports",
    component: () => import("@/views/ExportsView.vue"),
    meta: { title: "Exports" },
  },
  {
    path: "/settings",
    name: "settings",
    component: () => import("@/views/SettingsView.vue"),
    meta: { title: "Settings" },
  },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, from, saved) => saved || { top: 0 },
});

router.beforeEach((to) => {
  const auth = useAuthStore();

  // Wait for the startup refresh to settle before deciding anything.
  if (!auth.ready) return true;

  if (!auth.isAuthenticated && !to.meta.guest) {
    return { name: "sign-in", query: to.fullPath !== "/" ? { next: to.fullPath } : {} };
  }
  if (auth.isAuthenticated && to.meta.guest) return { name: "dashboard" };
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} — Reelcraft` : "Reelcraft";
});
