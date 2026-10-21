<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import { formatBytes } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useExportStore } from "@/stores/exports";

const auth = useAuthStore();
const exportStore = useExportStore();
const route = useRoute();
const router = useRouter();

const links = [
  { name: "dashboard", label: "Dashboard", icon: "dashboard" },
  { name: "upload", label: "Upload", icon: "upload" },
  { name: "videos", label: "Videos", icon: "film" },
  { name: "exports", label: "Exports", icon: "download" },
  { name: "settings", label: "Settings", icon: "settings" },
];

const activeCount = computed(() => exportStore.active.length);
const storageLabel = computed(() => {
  const usage = auth.usage;
  if (!usage) return "";
  return `${formatBytes(usage.storage_bytes_used)} of ${formatBytes(usage.storage_bytes_limit)}`;
});

function isActive(name) {
  if (name === "videos") return route.name === "videos" || route.name === "editor";
  return route.name === name;
}

async function signOut() {
  await auth.logout();
  exportStore.reset();
  router.push({ name: "sign-in" });
}
</script>

<template>
  <!-- Sidebar on desktop -->
  <aside class="hidden w-64 shrink-0 flex-col border-r border-ink-800 bg-ink-900 lg:flex">
    <div class="flex items-center gap-2.5 px-5 py-6">
      <span class="grid h-9 w-9 place-items-center rounded-xl bg-brand-500 text-white">
        <AppIcon name="film" :size="18" />
      </span>
      <span class="text-lg font-bold tracking-tight">Reelcraft</span>
    </div>

    <nav class="flex-1 space-y-1 px-3" aria-label="Main">
      <RouterLink
        v-for="link in links"
        :key="link.name"
        :to="{ name: link.name }"
        class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
        :class="
          isActive(link.name)
            ? 'bg-brand-500/15 text-brand-300'
            : 'text-mist-300 hover:bg-ink-800 hover:text-mist-100'
        "
      >
        <AppIcon :name="link.icon" :size="18" />
        <span>{{ link.label }}</span>
        <span
          v-if="link.name === 'exports' && activeCount > 0"
          class="ml-auto rounded-full bg-brand-500 px-2 py-0.5 text-xs font-semibold text-white"
          :aria-label="`${activeCount} rendering`"
        >
          {{ activeCount }}
        </span>
      </RouterLink>
    </nav>

    <div class="border-t border-ink-800 p-4">
      <div v-if="auth.usage" class="mb-3">
        <div class="mb-1.5 flex justify-between text-xs text-mist-500">
          <span>Storage</span>
          <span>{{ storageLabel }}</span>
        </div>
        <div class="h-1.5 overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full transition-all"
            :class="auth.storageUsedRatio > 0.9 ? 'bg-rose-400' : 'bg-brand-500'"
            :style="{ width: `${Math.max(2, auth.storageUsedRatio * 100)}%` }"
          />
        </div>
      </div>

      <p class="truncate text-sm font-medium" :title="auth.user?.email">{{ auth.displayName }}</p>
      <button type="button" class="btn-ghost mt-1 w-full justify-start px-2" @click="signOut">
        <AppIcon name="logout" :size="16" />
        Sign out
      </button>
    </div>
  </aside>

  <!-- Bottom tab bar on phones: thumb-reachable, which a sidebar is not -->
  <nav
    class="fixed inset-x-0 bottom-0 z-40 flex border-t border-ink-800 bg-ink-900/95 backdrop-blur lg:hidden"
    style="padding-bottom: env(safe-area-inset-bottom)"
    aria-label="Main"
  >
    <RouterLink
      v-for="link in links"
      :key="link.name"
      :to="{ name: link.name }"
      class="relative flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors"
      :class="isActive(link.name) ? 'text-brand-300' : 'text-mist-500'"
    >
      <AppIcon :name="link.icon" :size="20" />
      <span>{{ link.label }}</span>
      <span
        v-if="link.name === 'exports' && activeCount > 0"
        class="absolute right-1/4 top-1.5 h-2 w-2 rounded-full bg-brand-400"
        :aria-label="`${activeCount} rendering`"
      />
    </RouterLink>
  </nav>
</template>
