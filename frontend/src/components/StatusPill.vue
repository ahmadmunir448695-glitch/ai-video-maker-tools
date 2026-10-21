<script setup>
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { statusLabel } from "@/lib/format";

const props = defineProps({
  status: { type: String, required: true },
  progress: { type: Number, default: 0 },
});

const style = computed(
  () =>
    ({
      pending: { cls: "bg-ink-700 text-mist-300", icon: "clock" },
      queued: { cls: "bg-ink-700 text-mist-300", icon: "clock" },
      processing: { cls: "bg-brand-500/15 text-brand-300", icon: "spinner" },
      succeeded: { cls: "bg-mint-400/15 text-mint-400", icon: "check" },
      failed: { cls: "bg-rose-400/15 text-rose-400", icon: "alert" },
      cancelled: { cls: "bg-ink-700 text-mist-500", icon: "x" },
    })[props.status] || { cls: "bg-ink-700 text-mist-300", icon: "clock" },
);

const label = computed(() => {
  if (props.status === "processing" && props.progress > 0) {
    return `Working on it — ${props.progress}%`;
  }
  return statusLabel(props.status);
});
</script>

<template>
  <span class="chip" :class="style.cls">
    <AppIcon
      :name="style.icon"
      :size="13"
      :class="props.status === 'processing' ? 'animate-spin' : ''"
    />
    {{ label }}
  </span>
</template>
