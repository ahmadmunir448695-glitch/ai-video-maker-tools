<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import TrimControl from "@/components/TrimControl.vue";
import {
  aspectHint,
  aspectLabel,
  formatBytes,
  formatDuration,
  formatTimecode,
  qualityLabel,
  speedLabel,
} from "@/lib/format";
import { useExportStore } from "@/stores/exports";
import { useToastStore } from "@/stores/toasts";
import { useVideoStore } from "@/stores/videos";

const props = defineProps({ id: { type: String, required: true } });

const router = useRouter();
const videos = useVideoStore();
const exportStore = useExportStore();
const toasts = useToastStore();

const asset = ref(null);
const loading = ref(true);
const loadError = ref("");
const videoEl = ref(null);
const playing = ref(false);
const currentTime = ref(0);
const submitting = ref(false);
const estimate = ref(null);
const title = ref("");

/** The edit being composed. Sent to the server as the `spec`. */
const spec = reactive({
  trim: { start: 0, end: null },
  speed: 1,
  rotate: 0,
  aspect: "original",
  fit: "cover",
  quality: "medium",
  mute: false,
});

const options = computed(() => exportStore.options);
const speeds = computed(() => options.value?.speeds ?? [0.25, 0.5, 1, 1.5, 2]);
const aspects = computed(() => options.value?.aspects ?? ["original", "9:16", "1:1", "16:9"]);
const qualities = computed(() => options.value?.qualities ?? ["low", "medium", "high"]);

const duration = computed(() => asset.value?.duration_seconds ?? 0);
const trimEnd = computed(() => spec.trim.end ?? duration.value);

/** Mirror of the server's own aspect maths, used only to shape the preview box. */
const previewRatio = computed(() => {
  const ratios = { original: null, "9:16": 9 / 16, "1:1": 1, "16:9": 16 / 9, "4:5": 4 / 5 };
  const ratio = ratios[spec.aspect];
  if (ratio !== null && ratio !== undefined) return ratio;
  const width = asset.value?.width || 16;
  const height = asset.value?.height || 9;
  return width / height;
});

/**
 * Size the preview from its height rather than its width.
 *
 * A tall 9:16 box set only by aspect-ratio stretches to over 1000px on a
 * desktop column, pushing the controls off screen. Deriving the width from a
 * capped height keeps every shape visible at once; max-width then takes over
 * for wide ratios and on narrow screens.
 */
const previewAspectStyle = computed(() => ({
  aspectRatio: String(previewRatio.value),
  width: `calc(${previewRatio.value} * min(58vh, 32rem))`,
  maxWidth: "100%",
}));

const isDirty = computed(
  () =>
    spec.trim.start > 0 ||
    (spec.trim.end !== null && spec.trim.end < duration.value) ||
    spec.speed !== 1 ||
    spec.rotate !== 0 ||
    spec.aspect !== "original" ||
    spec.mute,
);

const existingExports = computed(() => exportStore.forSource(props.id));
const activeExport = computed(() => existingExports.value.find((job) => ["pending", "queued", "processing"].includes(job.status)));

onMounted(async () => {
  try {
    await exportStore.loadOptions();
    asset.value = videos.byId(props.id) || (await videos.fetchOne(props.id));
    spec.trim.end = asset.value.duration_seconds;
    title.value = asset.value.original_filename.replace(/\.[^.]+$/, "");
    await exportStore.load();
    refreshEstimate();
  } catch (error) {
    loadError.value = error.status === 404 ? "That video could not be found." : error.message;
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  if (estimateTimer) clearTimeout(estimateTimer);
});

/* ------------------------------------------------------------------ preview */

function togglePlay() {
  const element = videoEl.value;
  if (!element) return;
  if (element.paused) {
    // Start from the trim-in point, so "play" previews the selection.
    if (element.currentTime < spec.trim.start || element.currentTime >= trimEnd.value) {
      element.currentTime = spec.trim.start;
    }
    element.play();
  } else {
    element.pause();
  }
}

function onTimeUpdate() {
  const element = videoEl.value;
  if (!element) return;
  currentTime.value = element.currentTime;
  // Stop at the trim-out point so the preview reflects the edit, not the source.
  if (element.currentTime >= trimEnd.value) {
    element.pause();
    element.currentTime = spec.trim.start;
  }
}

function seek(seconds) {
  if (videoEl.value) videoEl.value.currentTime = seconds;
  currentTime.value = seconds;
}

/** Apply speed and mute to the preview element, so what you see matches. */
watch(
  () => spec.speed,
  (value) => {
    if (videoEl.value) videoEl.value.playbackRate = value;
  },
);
watch(
  () => spec.mute,
  (value) => {
    if (videoEl.value) videoEl.value.muted = value;
  },
);

/* ----------------------------------------------------------------- estimate */

let estimateTimer = null;

/**
 * Ask the server what this edit would produce. Debounced, because the trim
 * sliders fire continuously while dragging.
 */
function refreshEstimate() {
  if (estimateTimer) clearTimeout(estimateTimer);
  estimateTimer = setTimeout(async () => {
    if (!asset.value) return;
    try {
      estimate.value = await exportStore.preview({ sourceId: props.id, spec: serialiseSpec() });
    } catch {
      // An invalid in-progress edit (e.g. mid-drag) is not worth reporting;
      // the export button surfaces the real validation error on submit.
      estimate.value = null;
    }
  }, 350);
}

watch(() => [spec.trim.start, spec.trim.end, spec.speed, spec.aspect, spec.fit, spec.quality, spec.rotate, spec.mute], refreshEstimate);

function serialiseSpec() {
  return {
    trim: { start: Number(spec.trim.start.toFixed(2)), end: Number(trimEnd.value.toFixed(2)) },
    speed: spec.speed,
    rotate: spec.rotate,
    aspect: spec.aspect,
    fit: spec.fit,
    quality: spec.quality,
    mute: spec.mute,
  };
}

/* ------------------------------------------------------------------- export */

async function startExport() {
  submitting.value = true;
  try {
    const job = await exportStore.create({
      sourceId: props.id,
      spec: serialiseSpec(),
      title: title.value.trim(),
    });

    if (job.status === "succeeded") {
      toasts.success("That exact edit was already exported, so it is ready now.");
    } else {
      toasts.info("Export started. You can leave this page — we will keep working.");
    }
    router.push({ name: "exports" });
  } catch (error) {
    toasts.error(error.message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div v-if="loading" class="card grid place-items-center py-20 text-mist-500">
    <AppIcon name="spinner" :size="26" class="animate-spin" />
  </div>

  <div v-else-if="loadError" class="card p-6 text-center">
    <p class="text-rose-400">{{ loadError }}</p>
    <RouterLink :to="{ name: 'videos' }" class="btn-secondary mt-4">Back to your videos</RouterLink>
  </div>

  <div v-else>
    <PageHeader title="Editor" :description="asset.original_filename">
      <template #actions>
        <RouterLink :to="{ name: 'videos' }" class="btn-ghost">Back</RouterLink>
      </template>
    </PageHeader>

    <div
      v-if="activeExport"
      class="mb-5 card flex flex-wrap items-center gap-3 border-brand-400/40 bg-brand-500/5 p-4"
    >
      <StatusPill :status="activeExport.status" :progress="activeExport.progress" />
      <span class="text-sm text-mist-300">An export of this video is already running.</span>
      <RouterLink :to="{ name: 'exports' }" class="btn-ghost ml-auto">View exports</RouterLink>
    </div>

    <div class="grid gap-5 lg:grid-cols-5">
      <!-- Preview -->
      <section class="lg:col-span-3">
        <div class="card overflow-hidden">
          <div
            class="relative mx-auto flex items-center justify-center bg-black"
            :style="previewAspectStyle"
          >
            <!-- object-cover/contain mirrors the server's crop vs letterbox choice -->
            <video
              ref="videoEl"
              :src="asset.file_url"
              :poster="asset.thumbnail_url || undefined"
              class="h-full w-full"
              :class="spec.fit === 'cover' ? 'object-cover' : 'object-contain'"
              :style="spec.rotate ? { transform: `rotate(${spec.rotate}deg)` } : {}"
              playsinline
              preload="metadata"
              :muted="spec.mute"
              @timeupdate="onTimeUpdate"
              @play="playing = true"
              @pause="playing = false"
              @loadedmetadata="videoEl.playbackRate = spec.speed"
            />
          </div>

          <div class="flex items-center gap-3 border-t border-ink-800 px-4 py-3">
            <button
              type="button"
              class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-500 text-white hover:bg-brand-400"
              :aria-label="playing ? 'Pause' : 'Play the trimmed selection'"
              @click="togglePlay"
            >
              <AppIcon :name="playing ? 'pause' : 'play'" :size="16" :filled="!playing" />
            </button>
            <span class="font-mono text-xs text-mist-500">
              {{ formatTimecode(currentTime) }} / {{ formatTimecode(duration) }}
            </span>
            <span class="ml-auto text-xs text-mist-500">
              Preview only — the export is rendered on the server.
            </span>
          </div>
        </div>

        <!-- What the export will be -->
        <div class="card mt-5 p-4">
          <h2 class="mb-3 text-sm font-semibold">Your export</h2>
          <dl class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt class="text-xs text-mist-500">Length</dt>
              <dd class="mt-0.5 font-medium">
                {{ estimate ? formatDuration(estimate.output_duration_seconds) : "—" }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-mist-500">Size</dt>
              <dd class="mt-0.5 font-medium">
                {{ estimate ? `${estimate.output_width}×${estimate.output_height}` : "—" }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-mist-500">Shape</dt>
              <dd class="mt-0.5 font-medium">{{ aspectLabel(spec.aspect) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-mist-500">Sound</dt>
              <dd class="mt-0.5 font-medium">
                {{ estimate ? (estimate.keeps_audio ? "Kept" : "None") : "—" }}
              </dd>
            </div>
          </dl>

          <p
            v-if="estimate?.existing_export_id"
            class="mt-3 flex items-start gap-2 rounded-xl bg-ink-850 px-3 py-2.5 text-xs text-mist-300"
          >
            <AppIcon name="check" :size="14" class="mt-0.5 shrink-0 text-mint-400" />
            You have already exported this exact edit. Exporting again will reuse it instead of
            rendering it twice.
          </p>
        </div>
      </section>

      <!-- Controls -->
      <section class="space-y-5 lg:col-span-2">
        <div class="card p-4">
          <TrimControl
            :duration="duration"
            :start="spec.trim.start"
            :end="trimEnd"
            :current-time="currentTime"
            @update:start="spec.trim.start = $event"
            @update:end="spec.trim.end = $event"
            @seek="seek"
          />
        </div>

        <div class="card p-4">
          <span class="label">Speed</span>
          <div class="grid grid-cols-5 gap-1.5">
            <button
              v-for="value in speeds"
              :key="value"
              type="button"
              class="segment-item border border-ink-600"
              :class="spec.speed === value ? 'segment-item-active border-brand-500' : ''"
              :aria-pressed="spec.speed === value"
              @click="spec.speed = value"
            >
              {{ speedLabel(value) }}
            </button>
          </div>
          <p class="mt-2.5 text-xs text-mist-500">
            {{
              spec.speed < 1
                ? "Slow motion. The clip gets longer and the sound is slowed to match."
                : spec.speed > 1
                  ? "Sped up. The clip gets shorter and the sound is sped up to match."
                  : "Plays at the original speed."
            }}
          </p>
        </div>

        <div class="card p-4">
          <span class="label">Shape</span>
          <div class="space-y-1.5">
            <button
              v-for="value in aspects"
              :key="value"
              type="button"
              class="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors"
              :class="
                spec.aspect === value
                  ? 'border-brand-500 bg-brand-500/10'
                  : 'border-ink-600 hover:bg-ink-800'
              "
              :aria-pressed="spec.aspect === value"
              @click="spec.aspect = value"
            >
              <span
                class="shrink-0 rounded border-2"
                :class="spec.aspect === value ? 'border-brand-400' : 'border-ink-500'"
                :style="{
                  width: value === '9:16' ? '12px' : value === '1:1' ? '20px' : '26px',
                  height: value === '9:16' ? '21px' : value === '1:1' ? '20px' : '15px',
                }"
              />
              <span class="min-w-0">
                <span class="block text-sm font-medium">{{ aspectLabel(value) }}</span>
                <span class="block text-xs text-mist-500">{{ aspectHint(value) }}</span>
              </span>
            </button>
          </div>

          <div v-if="spec.aspect !== 'original'" class="mt-3">
            <span class="label">When the shape does not match</span>
            <div class="segment">
              <button
                type="button"
                class="segment-item"
                :class="spec.fit === 'cover' ? 'segment-item-active' : ''"
                :aria-pressed="spec.fit === 'cover'"
                @click="spec.fit = 'cover'"
              >
                Fill &amp; crop
              </button>
              <button
                type="button"
                class="segment-item"
                :class="spec.fit === 'contain' ? 'segment-item-active' : ''"
                :aria-pressed="spec.fit === 'contain'"
                @click="spec.fit = 'contain'"
              >
                Fit &amp; add bars
              </button>
            </div>
          </div>
        </div>

        <div class="card p-4">
          <span class="label">Quality</span>
          <div class="space-y-1.5">
            <button
              v-for="value in qualities"
              :key="value"
              type="button"
              class="flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left text-sm transition-colors"
              :class="
                spec.quality === value
                  ? 'border-brand-500 bg-brand-500/10'
                  : 'border-ink-600 hover:bg-ink-800'
              "
              :aria-pressed="spec.quality === value"
              @click="spec.quality = value"
            >
              <span class="font-medium">{{ qualityLabel(value) }}</span>
              <AppIcon v-if="spec.quality === value" name="check" :size="15" class="text-brand-300" />
            </button>
          </div>

          <label class="mt-4 flex cursor-pointer items-center gap-2.5 text-sm">
            <input v-model="spec.mute" type="checkbox" class="h-4 w-4 rounded accent-brand-500" />
            <span>Remove the sound</span>
          </label>
          <p v-if="!asset.has_audio" class="mt-1.5 text-xs text-mist-500">
            This video has no sound track.
          </p>
        </div>

        <div class="card p-4">
          <label class="label" for="export-title">Name this export</label>
          <input
            id="export-title"
            v-model="title"
            class="input"
            maxlength="140"
            placeholder="My reel"
          />
        </div>

        <button
          type="button"
          class="btn-primary w-full"
          :disabled="submitting"
          @click="startExport"
        >
          <AppIcon v-if="submitting" name="spinner" :size="16" class="animate-spin" />
          <AppIcon v-else name="download" :size="16" />
          {{ submitting ? "Starting…" : "Export video" }}
        </button>
        <p class="text-center text-xs text-mist-500">
          Rendering happens on the server. You can close this page and come back.
        </p>
      </section>
    </div>
  </div>
</template>
