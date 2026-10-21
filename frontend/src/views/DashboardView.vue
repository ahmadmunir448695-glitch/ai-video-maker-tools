<script setup>
import { computed, onMounted } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import { formatBytes, formatDuration, formatRelativeTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useExportStore } from "@/stores/exports";
import { useVideoStore } from "@/stores/videos";

const auth = useAuthStore();
const videos = useVideoStore();
const exportStore = useExportStore();

onMounted(async () => {
  await Promise.allSettled([videos.load(), exportStore.load(), auth.loadProfile()]);
  if (exportStore.hasActive) exportStore.startPolling();
});

const stats = computed(() => [
  { label: "Videos", value: videos.count, icon: "film", to: { name: "videos" } },
  { label: "Exports ready", value: exportStore.finished.length, icon: "check", to: { name: "exports" } },
  { label: "Rendering", value: exportStore.active.length, icon: "spinner", to: { name: "exports" } },
  { label: "Needs attention", value: exportStore.failed.length, icon: "alert", to: { name: "exports" } },
]);

const recentVideos = computed(() => videos.items.slice(0, 3));
const recentExports = computed(() => exportStore.items.slice(0, 4));

/* Phase 2 onward. Shown as plainly unavailable rather than as working buttons:
   nothing here pretends to be connected. */
const comingSoon = [
  { label: "AI captions & hashtags", detail: "Phase 2", icon: "scissors" },
  { label: "Music & subtitles", detail: "Phase 2", icon: "film" },
  { label: "TikTok, Instagram & YouTube publishing", detail: "Phase 3", icon: "upload" },
  { label: "Content calendar & scheduling", detail: "Phase 4", icon: "clock" },
];
</script>

<template>
  <div>
    <PageHeader :title="`Hello, ${auth.displayName}`" description="Upload a video, edit it, and export it.">
      <template #actions>
        <RouterLink :to="{ name: 'upload' }" class="btn-primary">
          <AppIcon name="plus" :size="16" />
          Upload a video
        </RouterLink>
      </template>
    </PageHeader>

    <!-- Live render progress, surfaced first because it is the thing in motion -->
    <section v-if="exportStore.active.length" class="card mb-5 p-4">
      <h2 class="mb-3 text-sm font-semibold">Rendering now</h2>
      <div class="space-y-4">
        <div v-for="job in exportStore.active" :key="job.id">
          <div class="mb-1.5 flex items-center justify-between gap-3">
            <span class="truncate text-sm font-medium">{{ job.display_title }}</span>
            <StatusPill :status="job.status" :progress="job.progress" />
          </div>
          <ProgressBar :value="job.progress" />
        </div>
      </div>
    </section>

    <section class="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <RouterLink
        v-for="stat in stats"
        :key="stat.label"
        :to="stat.to"
        class="card p-4 transition-colors hover:border-ink-600 hover:bg-ink-850"
      >
        <span
          class="mb-2 grid h-8 w-8 place-items-center rounded-lg bg-ink-800 text-mist-300"
        >
          <AppIcon :name="stat.icon" :size="16" />
        </span>
        <p class="text-2xl font-bold">{{ stat.value }}</p>
        <p class="text-xs text-mist-500">{{ stat.label }}</p>
      </RouterLink>
    </section>

    <div class="grid gap-5 lg:grid-cols-2">
      <section>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">Your videos</h2>
          <RouterLink :to="{ name: 'videos' }" class="text-xs font-medium text-brand-300 hover:underline">
            See all
          </RouterLink>
        </div>

        <EmptyState
          v-if="!videos.loading && videos.count === 0"
          icon="upload"
          title="No videos yet"
          description="Upload one to get started. MP4, MOV, WebM and MKV all work."
        >
          <RouterLink :to="{ name: 'upload' }" class="btn-primary">Upload a video</RouterLink>
        </EmptyState>

        <ul v-else class="space-y-2">
          <li v-for="asset in recentVideos" :key="asset.id">
            <RouterLink
              :to="{ name: 'editor', params: { id: asset.id } }"
              class="card flex items-center gap-3 p-3 transition-colors hover:bg-ink-850"
            >
              <img
                v-if="asset.thumbnail_url"
                :src="asset.thumbnail_url"
                :alt="''"
                class="h-12 w-20 shrink-0 rounded-lg bg-ink-800 object-cover"
                loading="lazy"
              />
              <span v-else class="grid h-12 w-20 shrink-0 place-items-center rounded-lg bg-ink-800 text-mist-500">
                <AppIcon name="film" :size="16" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium">{{ asset.original_filename }}</span>
                <span class="block text-xs text-mist-500">
                  {{ formatDuration(asset.duration_seconds) }} · {{ asset.width }}×{{ asset.height }}
                </span>
              </span>
              <AppIcon name="scissors" :size="16" class="shrink-0 text-mist-500" />
            </RouterLink>
          </li>
        </ul>
      </section>

      <section>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">Recent exports</h2>
          <RouterLink :to="{ name: 'exports' }" class="text-xs font-medium text-brand-300 hover:underline">
            See all
          </RouterLink>
        </div>

        <EmptyState
          v-if="!exportStore.loading && exportStore.items.length === 0"
          icon="download"
          title="Nothing exported yet"
          description="Open a video in the editor and export it to see it here."
        />

        <ul v-else class="space-y-2">
          <li v-for="job in recentExports" :key="job.id" class="card p-3">
            <div class="flex items-center justify-between gap-3">
              <span class="min-w-0">
                <span class="block truncate text-sm font-medium">{{ job.display_title }}</span>
                <span class="block text-xs text-mist-500">{{ formatRelativeTime(job.created_at) }}</span>
              </span>
              <StatusPill :status="job.status" :progress="job.progress" />
            </div>
          </li>
        </ul>
      </section>
    </div>

    <section class="mt-5">
      <div class="card p-4">
        <div class="mb-1 flex items-center justify-between">
          <h2 class="text-sm font-semibold">Storage</h2>
          <span v-if="auth.usage" class="text-xs text-mist-500">
            {{ formatBytes(auth.usage.storage_bytes_used) }} of
            {{ formatBytes(auth.usage.storage_bytes_limit) }}
          </span>
        </div>
        <ProgressBar
          v-if="auth.usage"
          :value="auth.storageUsedRatio * 100"
          :tone="auth.storageUsedRatio > 0.9 ? 'rose' : 'brand'"
        />
        <p v-if="auth.usage" class="mt-2 text-xs text-mist-500">
          {{ auth.usage.exports_today }} of {{ auth.usage.exports_per_day_limit }} exports used today.
        </p>
      </div>
    </section>

    <section class="mt-5">
      <h2 class="mb-3 text-sm font-semibold">Coming next</h2>
      <ul class="grid gap-2 sm:grid-cols-2">
        <li
          v-for="item in comingSoon"
          :key="item.label"
          class="flex items-center gap-3 rounded-xl border border-ink-800 bg-ink-900/50 px-3.5 py-3"
        >
          <span class="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink-850 text-mist-500">
            <AppIcon :name="item.icon" :size="15" />
          </span>
          <span class="min-w-0 flex-1 text-sm text-mist-300">{{ item.label }}</span>
          <span class="chip shrink-0 bg-ink-800 text-mist-500">{{ item.detail }}</span>
        </li>
      </ul>
      <p class="mt-2.5 text-xs text-mist-500">
        These are not built yet. Publishing needs each platform's own approved developer app, so it
        arrives in Phase 3.
      </p>
    </section>
  </div>
</template>
