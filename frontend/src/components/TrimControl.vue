<script setup>
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { formatTimecode } from "@/lib/format";

/**
 * Two range sliders over a shared track, which is the most reliable way to get
 * a draggable in/out selection that still works with touch and a keyboard.
 */
const props = defineProps({
  duration: { type: Number, required: true },
  start: { type: Number, required: true },
  end: { type: Number, required: true },
  currentTime: { type: Number, default: 0 },
});

const emit = defineEmits(["update:start", "update:end", "seek"]);

const MIN_SELECTION = 0.1;

const startPercent = computed(() => (props.duration ? (props.start / props.duration) * 100 : 0));
const endPercent = computed(() => (props.duration ? (props.end / props.duration) * 100 : 100));
const playheadPercent = computed(() =>
  props.duration ? Math.min(100, (props.currentTime / props.duration) * 100) : 0,
);
const selectedDuration = computed(() => Math.max(0, props.end - props.start));

function onStart(event) {
  const value = Number(event.target.value);
  // Never let the handles cross, or the selection would invert.
  emit("update:start", Math.min(value, props.end - MIN_SELECTION));
  emit("seek", Math.min(value, props.end - MIN_SELECTION));
}

function onEnd(event) {
  const value = Number(event.target.value);
  emit("update:end", Math.max(value, props.start + MIN_SELECTION));
  emit("seek", Math.max(value, props.start + MIN_SELECTION));
}

function reset() {
  emit("update:start", 0);
  emit("update:end", props.duration);
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <span class="label mb-0">Trim</span>
      <button
        v-if="props.start > 0 || props.end < props.duration"
        type="button"
        class="text-xs font-medium text-brand-300 hover:underline"
        @click="reset"
      >
        Use the whole video
      </button>
    </div>

    <!-- Visual track: selected region highlighted, playhead on top -->
    <div class="relative mb-1 h-10 overflow-hidden rounded-xl bg-ink-850">
      <div
        class="absolute inset-y-0 bg-brand-500/25 border-x-2 border-brand-400"
        :style="{ left: `${startPercent}%`, width: `${Math.max(0, endPercent - startPercent)}%` }"
      />
      <div
        class="absolute inset-y-0 w-0.5 bg-white"
        :style="{ left: `${playheadPercent}%` }"
        aria-hidden="true"
      />
    </div>

    <!-- The two handles. Stacked so both remain reachable. -->
    <div class="space-y-2">
      <div class="flex items-center gap-3">
        <span class="w-10 shrink-0 text-xs font-medium text-mist-500">Start</span>
        <input
          type="range"
          :min="0"
          :max="props.duration"
          step="0.1"
          :value="props.start"
          aria-label="Trim start"
          @input="onStart"
        />
        <span class="w-14 shrink-0 text-right font-mono text-xs text-mist-300">
          {{ formatTimecode(props.start) }}
        </span>
      </div>

      <div class="flex items-center gap-3">
        <span class="w-10 shrink-0 text-xs font-medium text-mist-500">End</span>
        <input
          type="range"
          :min="0"
          :max="props.duration"
          step="0.1"
          :value="props.end"
          aria-label="Trim end"
          @input="onEnd"
        />
        <span class="w-14 shrink-0 text-right font-mono text-xs text-mist-300">
          {{ formatTimecode(props.end) }}
        </span>
      </div>
    </div>

    <p class="mt-2.5 flex items-center gap-1.5 text-xs text-mist-500">
      <AppIcon name="scissors" :size="13" />
      Keeping {{ formatTimecode(selectedDuration) }} of {{ formatTimecode(props.duration) }}
    </p>
  </div>
</template>
