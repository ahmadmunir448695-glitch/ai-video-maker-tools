<script setup>
const props = defineProps({
  value: { type: Number, default: 0 },
  label: { type: String, default: "" },
  tone: { type: String, default: "brand" },
});

const tones = {
  brand: "bg-brand-500",
  mint: "bg-mint-400",
  rose: "bg-rose-400",
};
</script>

<template>
  <div>
    <div v-if="props.label" class="mb-1.5 flex justify-between text-xs text-mist-500">
      <span>{{ props.label }}</span>
      <span>{{ Math.round(props.value) }}%</span>
    </div>
    <div
      class="h-2 overflow-hidden rounded-full bg-ink-800"
      role="progressbar"
      :aria-valuenow="Math.round(props.value)"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="props.label || 'Progress'"
    >
      <div
        class="h-full rounded-full transition-[width] duration-300"
        :class="tones[props.tone] || tones.brand"
        :style="{ width: `${Math.max(0, Math.min(100, props.value))}%` }"
      />
    </div>
  </div>
</template>
