<script setup>
import { onMounted, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { formatBytes, formatDuration, formatRelativeTime } from "@/lib/format";
import { useToastStore } from "@/stores/toasts";
import { useVideoStore } from "@/stores/videos";

const videos = useVideoStore();
const toasts = useToastStore();

/** Id awaiting a second tap, so deleting needs a deliberate confirm. */
const confirmingId = ref(null);
const workingId = ref(null);

onMounted(() => videos.load({ force: true }));

async function remove(asset) {
  if (confirmingId.value !== asset.id) {
    confirmingId.value = asset.id;
    setTimeout(() => {
      if (confirmingId.value === asset.id) confirmingId.value = null;
    }, 4000);
    return;
  }

  confirmingId.value = null;
  workingId.value = asset.id;
  try {
    await videos.remove(asset.id);
    toasts.success(`"${asset.original_filename}" was deleted.`);
  } catch (error) {
    toasts.error(error.message);
  } finally {
    workingId.value = null;
  }
}

async function download(asset) {
  try {
    const { url } = await videos.downloadUrl(asset.id);
    window.open(url, "_blank", "noopener");
  } catch (error) {
    toasts.error(error.message);
  }
}
</script>

<template>
  <div>
    <PageHeader title="Your videos" description="Everything you have uploaded.">
      <template #actions>
        <RouterLink :to="{ name: 'upload' }" class="btn-primary">
          <AppIcon name="plus" :size="16" />
          Upload
        </RouterLink>
      </template>
    </PageHeader>

    <div v-if="videos.loading && !videos.loaded" class="card grid place-items-center py-16 text-mist-500">
      <AppIcon name="spinner" :size="24" class="animate-spin" />
    </div>

    <EmptyState
      v-else-if="videos.count === 0"
      icon="film"
      title="No videos yet"
      description="Upload a video and it will appear here, ready to edit."
    >
      <RouterLink :to="{ name: 'upload' }" class="btn-primary">Upload a video</RouterLink>
    </EmptyState>

    <ul v-else class="grid gap-3 sm:grid-cols-2">
      <li v-for="asset in videos.items" :key="asset.id" class="card overflow-hidden">
        <RouterLink :to="{ name: 'editor', params: { id: asset.id } }" class="block">
          <div class="relative aspect-video bg-ink-850">
            <img
              v-if="asset.thumbnail_url"
              :src="asset.thumbnail_url"
              alt=""
              class="h-full w-full object-cover"
              loading="lazy"
            />
            <span v-else class="grid h-full place-items-center text-mist-500">
              <AppIcon name="film" :size="28" />
            </span>
            <span
              class="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 font-mono text-xs"
            >
              {{ formatDuration(asset.duration_seconds) }}
            </span>
          </div>
        </RouterLink>

        <div class="p-3.5">
          <p class="truncate text-sm font-medium" :title="asset.original_filename">
            {{ asset.original_filename }}
          </p>
          <p class="mt-0.5 text-xs text-mist-500">
            {{ asset.width }}×{{ asset.height }} · {{ formatBytes(asset.size_bytes) }} ·
            {{ formatRelativeTime(asset.created_at) }}
          </p>

          <div class="mt-3 flex flex-wrap gap-2">
            <RouterLink :to="{ name: 'editor', params: { id: asset.id } }" class="btn-primary flex-1">
              <AppIcon name="scissors" :size="15" />
              Edit
            </RouterLink>
            <button type="button" class="btn-secondary" aria-label="Download the original" @click="download(asset)">
              <AppIcon name="download" :size="15" />
            </button>
            <button
              type="button"
              class="btn-danger"
              :disabled="workingId === asset.id"
              @click="remove(asset)"
            >
              <AppIcon :name="workingId === asset.id ? 'spinner' : 'trash'" :size="15"
                :class="workingId === asset.id ? 'animate-spin' : ''" />
              <span v-if="confirmingId === asset.id" class="text-xs">Tap again</span>
            </button>
          </div>
          <p v-if="confirmingId === asset.id" class="mt-2 text-xs text-rose-400">
            This also deletes every export made from it.
          </p>
        </div>
      </li>
    </ul>
  </div>
</template>
