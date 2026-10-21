<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: "" },
});
</script>

<template>
  <header class="mb-6 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-2xl font-bold tracking-tight sm:text-3xl">{{ title }}</h1>
      <p v-if="description" class="mt-1 text-sm text-mist-500">{{ description }}</p>
    </div>
    <div class="flex items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
