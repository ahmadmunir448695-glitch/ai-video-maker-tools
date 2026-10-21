<script setup>
import AppIcon from "@/components/AppIcon.vue";
import { useToastStore } from "@/stores/toasts";

const toasts = useToastStore();

const tones = {
  success: { cls: "border-mint-400/40 bg-mint-400/10 text-mint-400", icon: "check" },
  error: { cls: "border-rose-400/40 bg-rose-400/10 text-rose-400", icon: "alert" },
  info: { cls: "border-ink-600 bg-ink-800 text-mist-100", icon: "clock" },
};
</script>

<template>
  <!-- aria-live so screen readers announce renders finishing and errors -->
  <div
    class="pointer-events-none fixed inset-x-3 bottom-20 z-50 flex flex-col items-center gap-2 lg:bottom-6 lg:left-auto lg:right-6 lg:items-end"
    role="status"
    aria-live="polite"
  >
    <TransitionGroup
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-2 opacity-0"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0"
    >
      <div
        v-for="toast in toasts.items"
        :key="toast.id"
        class="pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-xl border px-3.5 py-3 text-sm shadow-lg shadow-black/30 backdrop-blur"
        :class="(tones[toast.kind] || tones.info).cls"
      >
        <AppIcon :name="(tones[toast.kind] || tones.info).icon" :size="16" class="mt-0.5 shrink-0" />
        <span class="flex-1">{{ toast.message }}</span>
        <button
          type="button"
          class="shrink-0 opacity-60 hover:opacity-100"
          aria-label="Dismiss"
          @click="toasts.dismiss(toast.id)"
        >
          <AppIcon name="x" :size="14" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>
