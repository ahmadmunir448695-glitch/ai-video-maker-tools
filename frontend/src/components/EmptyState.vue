<script setup>
import AppIcon from "@/components/AppIcon.vue";

defineProps({
  icon: { type: String, default: "film" },
  title: { type: String, required: true },
  description: { type: String, default: "" },
});
</script>

<template>
  <div class="card flex flex-col items-center px-6 py-14 text-center">
    <span class="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-ink-800 text-mist-500">
      <AppIcon :name="icon" :size="26" />
    </span>
    <h3 class="text-base font-semibold">{{ title }}</h3>
    <p v-if="description" class="mt-1.5 max-w-sm text-sm text-mist-500">{{ description }}</p>
    <div class="mt-5">
      <slot />
    </div>
  </div>
</template>
