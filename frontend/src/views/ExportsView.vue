<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import { aspectLabel, formatBytes, formatDuration, formatRelativeTime, speedLabel } from "@/lib/format";
import { useExportStore } from "@/stores/exports";
import { useToastStore } from "@/stores/toasts";

const exportStore = useExportStore();
const toasts = useToastStore();

const filter = ref("all");
const workingId = ref(null);
const confirmingId = ref(null);

const filters = [
  { key: "all", label: "All" },
  { key: "active", label: "Rendering" },
  { key: "succeeded", label: "Ready" },
  { key: "failed", label: "Failed" },
];

const visible = computed(() => {
  if (filter.value === "active") return exportStore.active;
  if (filter.value === "succeeded") return exportStore.finished;
  if (filter.value === "failed") return exportStore.failed;
  return exportStore.items;
});

onMounted(async () => {
  await exportStore.load({ force: true });
  if (exportStore.hasActive) exportStore.startPolling();
});

// Stop the timer when the page is left; App.vue restarts it if work remains.
onUnmounted(() => exportStore.stopPolling());

function describe(job) {
  const spec = job.spec || {};
  const parts = [];
  if (spec.trim && (spec.trim.start > 0 || spec.trim.end)) {
    parts.push(`trimmed to ${formatDuration(job.output_duration_seconds || 0)}`);
  }
  if (spec.speed && spec.speed !== 1) parts.push(speedLabel(spec.speed));
  if (spec.aspect && spec.aspect !== "original") parts.push(aspectLabel(spec.aspect));
  if (spec.mute) parts.push("no sound");
  return parts.join(" · ") || "No changes";
}

async function act(job, action, successMessage) {
  workingId.value = job.id;
  try {
    await action();
    if (successMessage) toasts.success(successMessage);
  } catch (error) {
    toasts.error(error.message);
  } finally {
    workingId.value = null;
  }
}

async function download(job) {
  await act(job, async () => {
    const { url } = await exportStore.downloadUrl(job.id);
    window.open(url, "_blank", "noopener");
  });
}

function cancel(job) {
  return act(job, () => exportStore.cancel(job.id), "Export cancelled.");
}

function retry(job) {
  return act(job, () => exportStore.retry(job.id), "Trying that export again.");
}

async function remove(job) {
  if (confirmingId.value !== job.id) {
    confirmingId.value = job.id;
    setTimeout(() => {
      if (confirmingId.value === job.id) confirmingId.value = null;
    }, 4000);
    return;
  }
  confirmingId.value = null;
  await act(job, () => exportStore.remove(job.id), "Export deleted.");
}
</script>

<template>
  <div>
    <PageHeader title="Exports" description="Your rendered videos, and anything still being worked on.">
      <template #actions>
        <button type="button" class="btn-secondary" @click="exportStore.load({ force: true })">
          <AppIcon name="retry" :size="15" />
          Refresh
        </button>
      </template>
    </PageHeader>

    <div class="segment mb-5 max-w-md">
      <button
        v-for="item in filters"
        :key="item.key"
        type="button"
        class="segment-item"
        :class="filter === item.key ? 'segment-item-active' : ''"
        :aria-pressed="filter === item.key"
        @click="filter = item.key"
      >
        {{ item.label }}
      </button>
    </div>

    <div v-if="exportStore.loading && !exportStore.loaded" class="card grid place-items-center py-16 text-mist-500">
      <AppIcon name="spinner" :size="24" class="animate-spin" />
    </div>

    <EmptyState
      v-else-if="visible.length === 0"
      icon="download"
      title="Nothing here"
      :description="
        filter === 'all'
          ? 'Open a video in the editor and export it.'
          : 'No exports match this filter.'
      "
    >
      <RouterLink v-if="filter === 'all'" :to="{ name: 'videos' }" class="btn-primary">
        Go to your videos
      </RouterLink>
    </EmptyState>

    <ul v-else class="space-y-3">
      <li v-for="job in visible" :key="job.id" class="card p-4">
        <div class="flex items-start gap-3.5">
          <img
            v-if="job.thumbnail_url"
            :src="job.thumbnail_url"
            alt=""
            class="hidden h-16 w-24 shrink-0 rounded-lg bg-ink-850 object-cover sm:block"
            loading="lazy"
          />

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="truncate font-medium">{{ job.display_title }}</p>
              <StatusPill :status="job.status" :progress="job.progress" />
            </div>

            <p class="mt-1 text-xs text-mist-500">
              {{ describe(job) }}
              <span v-if="job.status === 'succeeded'">
                · {{ job.output_width }}×{{ job.output_height }} ·
                {{ formatBytes(job.output_size_bytes) }}
              </span>
              · {{ formatRelativeTime(job.created_at) }}
            </p>

            <div v-if="['pending', 'queued', 'processing'].includes(job.status)" class="mt-3">
              <ProgressBar :value="job.progress" />
            </div>

            <p
              v-if="job.status === 'failed' && job.error_message"
              class="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/40 bg-rose-400/10 px-3 py-2.5 text-xs text-rose-400"
            >
              <AppIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
              <span>{{ job.error_message }}</span>
            </p>

            <div class="mt-3.5 flex flex-wrap gap-2">
              <button
                v-if="job.status === 'succeeded'"
                type="button"
                class="btn-primary"
                :disabled="workingId === job.id"
                @click="download(job)"
              >
                <AppIcon name="download" :size="15" />
                Download
              </button>

              <button
                v-if="job.is_cancellable"
                type="button"
                class="btn-secondary"
                :disabled="workingId === job.id"
                @click="cancel(job)"
              >
                <AppIcon name="x" :size="15" />
                Cancel
              </button>

              <button
                v-if="job.can_retry"
                type="button"
                class="btn-secondary"
                :disabled="workingId === job.id"
                @click="retry(job)"
              >
                <AppIcon name="retry" :size="15" />
                Try again
              </button>

              <RouterLink
                :to="{ name: 'editor', params: { id: job.source_id } }"
                class="btn-ghost"
              >
                <AppIcon name="scissors" :size="15" />
                Edit again
              </RouterLink>

              <button
                v-if="!job.is_cancellable"
                type="button"
                class="btn-danger ml-auto"
                :disabled="workingId === job.id"
                @click="remove(job)"
              >
                <AppIcon name="trash" :size="15" />
                <span v-if="confirmingId === job.id" class="text-xs">Tap again</span>
              </button>
            </div>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
