<script setup>
import { computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";

import AppNav from "@/components/AppNav.vue";
import ToastStack from "@/components/ToastStack.vue";
import { useAuthStore } from "@/stores/auth";
import { useExportStore } from "@/stores/exports";

const auth = useAuthStore();
const exportStore = useExportStore();
const route = useRoute();

const showShell = computed(() => auth.isAuthenticated && !route.meta.guest);

// Resume polling after a reload if anything was still rendering, so progress
// keeps moving without the user having to open the exports page.
async function resumeActiveRenders() {
  if (!auth.isAuthenticated) return;
  try {
    await exportStore.load();
    if (exportStore.hasActive) exportStore.startPolling();
  } catch {
    // A failure here is not worth interrupting the user over; the page they
    // land on will load its own data and surface any real problem.
  }
}

onMounted(resumeActiveRenders);
watch(() => auth.isAuthenticated, (signedIn) => (signedIn ? resumeActiveRenders() : exportStore.reset()));
</script>

<template>
  <div class="flex min-h-full">
    <AppNav v-if="showShell" />

    <main
      class="min-w-0 flex-1"
      :class="showShell ? 'pb-24 lg:pb-0' : ''"
    >
      <div :class="showShell ? 'mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8' : ''">
        <RouterView v-slot="{ Component }">
          <Transition
            mode="out-in"
            enter-active-class="transition-opacity duration-150"
            enter-from-class="opacity-0"
            leave-active-class="transition-opacity duration-100"
            leave-to-class="opacity-0"
          >
            <component :is="Component" />
          </Transition>
        </RouterView>
      </div>
    </main>

    <ToastStack />
  </div>
</template>
