<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { formatBytes, formatDuration } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useExportStore } from "@/stores/exports";
import { useToastStore } from "@/stores/toasts";
import { useVideoStore } from "@/stores/videos";

const router = useRouter();
const videos = useVideoStore();
const exportStore = useExportStore();
const auth = useAuthStore();
const toasts = useToastStore();

const fileInput = ref(null);
const dragging = ref(false);
const localError = ref("");

const limits = computed(() => exportStore.options);
const maxBytes = computed(() => limits.value?.max_upload_bytes ?? auth.usage?.max_upload_bytes ?? 0);
const maxSeconds = computed(
  () => limits.value?.max_upload_duration_seconds ?? auth.usage?.max_upload_duration_seconds ?? 0,
);
const extensions = computed(() => limits.value?.allowed_extensions ?? ["mp4", "mov", "webm", "mkv"]);
const accept = computed(() => extensions.value.map((ext) => `.${ext}`).join(","));

onMounted(() => exportStore.loadOptions().catch(() => {}));

/**
 * Check what the browser can see before sending anything.
 *
 * This is a courtesy to the user, not a security control — the server re-checks
 * size, type and the actual bytes regardless.
 */
function preCheck(file) {
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  if (!extensions.value.includes(extension)) {
    return `"${extension || file.name}" is not a supported format. Use ${extensions.value.join(", ")}.`;
  }
  if (maxBytes.value && file.size > maxBytes.value) {
    return `That file is ${formatBytes(file.size)}. The limit is ${formatBytes(maxBytes.value)}.`;
  }
  return "";
}

async function handleFile(file) {
  if (!file) return;
  localError.value = "";
  videos.clearUploadError();

  const problem = preCheck(file);
  if (problem) {
    localError.value = problem;
    return;
  }

  try {
    const asset = await videos.uploadFile(file);
    // Refresh usage so the storage figure in the sidebar is not left stale.
    auth.loadProfile().catch(() => {});
    toasts.success(`"${asset.original_filename}" is ready to edit.`);
    router.push({ name: "editor", params: { id: asset.id } });
  } catch (error) {
    if (error.code !== "aborted") toasts.error(error.message);
  }
}

function onDrop(event) {
  dragging.value = false;
  handleFile(event.dataTransfer?.files?.[0]);
}

function onSelect(event) {
  handleFile(event.target.files?.[0]);
  // Reset, so picking the same file again still fires a change event.
  event.target.value = "";
}

const errorMessage = computed(() => localError.value || videos.upload.error);
</script>

<template>
  <div>
    <PageHeader
      title="Upload a video"
      description="Pick a video from your phone or computer. We check it can be edited before you go on."
    />

    <!-- Upload in progress -->
    <div v-if="videos.upload.active" class="card p-6">
      <div class="mb-4 flex items-center gap-3">
        <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-500/15 text-brand-300">
          <AppIcon name="spinner" :size="20" class="animate-spin" />
        </span>
        <div class="min-w-0">
          <p class="truncate font-medium">{{ videos.upload.filename }}</p>
          <p class="text-sm text-mist-500">
            {{ videos.upload.progress >= 99 ? "Checking the video…" : "Uploading…" }}
          </p>
        </div>
      </div>

      <ProgressBar :value="videos.upload.progress" />

      <p class="mt-3 text-xs text-mist-500">
        Keep this page open until it finishes.
      </p>
      <button type="button" class="btn-secondary mt-4" @click="videos.cancelUpload()">
        <AppIcon name="x" :size="16" />
        Cancel upload
      </button>
    </div>

    <!-- Drop zone -->
    <div v-else>
      <div
        class="card border-2 border-dashed p-8 text-center transition-colors sm:p-12"
        :class="dragging ? 'border-brand-400 bg-brand-500/5' : 'border-ink-600'"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <span class="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-ink-800 text-brand-300">
          <AppIcon name="upload" :size="28" />
        </span>

        <h2 class="text-lg font-semibold">Choose a video</h2>
        <p class="mx-auto mt-1.5 max-w-sm text-sm text-mist-500">
          <span class="hidden sm:inline">Drag it here, or </span>pick one from your device.
        </p>

        <button type="button" class="btn-primary mt-5" @click="fileInput?.click()">
          <AppIcon name="plus" :size="16" />
          Select a video
        </button>

        <input
          ref="fileInput"
          type="file"
          :accept="accept"
          class="hidden"
          @change="onSelect"
        />

        <dl class="mx-auto mt-8 grid max-w-md grid-cols-2 gap-3 text-left text-xs sm:grid-cols-3">
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-mist-500">Formats</dt>
            <dd class="mt-0.5 font-medium uppercase">{{ extensions.join(", ") }}</dd>
          </div>
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-mist-500">Max size</dt>
            <dd class="mt-0.5 font-medium">{{ maxBytes ? formatBytes(maxBytes) : "—" }}</dd>
          </div>
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-mist-500">Max length</dt>
            <dd class="mt-0.5 font-medium">{{ maxSeconds ? formatDuration(maxSeconds) : "—" }}</dd>
          </div>
        </dl>
      </div>

      <p
        v-if="errorMessage"
        class="mt-4 flex items-start gap-2.5 rounded-xl border border-rose-400/40 bg-rose-400/10 px-3.5 py-3 text-sm text-rose-400"
        role="alert"
      >
        <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
        <span>{{ errorMessage }}</span>
      </p>

      <div v-if="auth.usage" class="mt-6 card p-4">
        <div class="mb-2 flex justify-between text-sm">
          <span class="text-mist-300">Storage used</span>
          <span class="text-mist-500">
            {{ formatBytes(auth.usage.storage_bytes_used) }} of
            {{ formatBytes(auth.usage.storage_bytes_limit) }}
          </span>
        </div>
        <ProgressBar
          :value="auth.storageUsedRatio * 100"
          :tone="auth.storageUsedRatio > 0.9 ? 'rose' : 'brand'"
        />
      </div>
    </div>
  </div>
</template>
