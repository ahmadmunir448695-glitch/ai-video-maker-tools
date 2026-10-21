<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { formatBytes, formatDuration } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useExportStore } from "@/stores/exports";
import { useToastStore } from "@/stores/toasts";

const auth = useAuthStore();
const exportStore = useExportStore();
const toasts = useToastStore();
const router = useRouter();

const displayName = ref(auth.user?.display_name || "");
const savingName = ref(false);

const password = reactive({ current: "", next: "" });
const savingPassword = ref(false);
const passwordError = ref("");

onMounted(async () => {
  await Promise.allSettled([auth.loadProfile(), exportStore.loadOptions()]);
  displayName.value = auth.user?.display_name || "";
});

async function saveName() {
  savingName.value = true;
  try {
    await auth.updateDisplayName(displayName.value.trim());
    toasts.success("Your name was updated.");
  } catch (error) {
    toasts.error(error.message);
  } finally {
    savingName.value = false;
  }
}

async function savePassword() {
  passwordError.value = "";
  savingPassword.value = true;
  try {
    await auth.changePassword({ currentPassword: password.current, newPassword: password.next });
    password.current = "";
    password.next = "";
    toasts.success("Your password was changed.");
  } catch (error) {
    passwordError.value = error.fieldError("new_password") || error.fieldError("current_password") || error.message;
  } finally {
    savingPassword.value = false;
  }
}

async function signOut() {
  await auth.logout();
  exportStore.reset();
  router.push({ name: "sign-in" });
}
</script>

<template>
  <div>
    <PageHeader title="Settings" description="Your account and the limits on your plan." />

    <div class="space-y-5">
      <section class="card p-5">
        <h2 class="text-sm font-semibold">Your account</h2>
        <p class="mt-1 text-xs text-mist-500">{{ auth.user?.email }}</p>

        <div class="mt-4 flex flex-wrap items-end gap-3">
          <div class="min-w-48 flex-1">
            <label class="label" for="display-name">Name</label>
            <input id="display-name" v-model.trim="displayName" class="input" maxlength="80" />
          </div>
          <button type="button" class="btn-secondary" :disabled="savingName" @click="saveName">
            <AppIcon v-if="savingName" name="spinner" :size="15" class="animate-spin" />
            Save
          </button>
        </div>
      </section>

      <section class="card p-5">
        <h2 class="text-sm font-semibold">Change your password</h2>
        <form class="mt-4 space-y-3" novalidate @submit.prevent="savePassword">
          <div>
            <label class="label" for="current-password">Current password</label>
            <input
              id="current-password"
              v-model="password.current"
              class="input"
              type="password"
              autocomplete="current-password"
              required
            />
          </div>
          <div>
            <label class="label" for="new-password">New password</label>
            <input
              id="new-password"
              v-model="password.next"
              class="input"
              type="password"
              autocomplete="new-password"
              required
            />
            <p class="mt-1.5 text-xs text-mist-500">At least 10 characters.</p>
          </div>

          <p v-if="passwordError" class="field-error" role="alert">{{ passwordError }}</p>

          <button
            type="submit"
            class="btn-secondary"
            :disabled="savingPassword || !password.current || !password.next"
          >
            <AppIcon v-if="savingPassword" name="spinner" :size="15" class="animate-spin" />
            Change password
          </button>
        </form>
      </section>

      <section v-if="auth.usage" class="card p-5">
        <h2 class="text-sm font-semibold">Your plan</h2>
        <p class="mt-1 text-xs capitalize text-mist-500">{{ auth.user?.plan }} plan</p>

        <div class="mt-4">
          <div class="mb-1.5 flex justify-between text-sm">
            <span class="text-mist-300">Storage</span>
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

        <dl class="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-xs text-mist-500">Exports today</dt>
            <dd class="mt-0.5 font-medium">
              {{ auth.usage.exports_today }} / {{ auth.usage.exports_per_day_limit }}
            </dd>
          </div>
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-xs text-mist-500">At once</dt>
            <dd class="mt-0.5 font-medium">{{ auth.usage.concurrent_render_limit }} renders</dd>
          </div>
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-xs text-mist-500">Max upload</dt>
            <dd class="mt-0.5 font-medium">{{ formatBytes(auth.usage.max_upload_bytes) }}</dd>
          </div>
          <div class="rounded-xl bg-ink-850 px-3 py-2.5">
            <dt class="text-xs text-mist-500">Max length</dt>
            <dd class="mt-0.5 font-medium">
              {{ formatDuration(auth.usage.max_upload_duration_seconds) }}
            </dd>
          </div>
        </dl>

        <p class="mt-3 text-xs text-mist-500">
          Paid plans and higher limits are not available yet.
        </p>
      </section>

      <section class="card p-5">
        <h2 class="text-sm font-semibold">Connected accounts</h2>
        <p class="mt-1.5 text-sm text-mist-500">
          Publishing to TikTok, Instagram and YouTube is not built yet. Each platform requires its
          own developer application and review before it can be connected, so this arrives in
          Phase 3.
        </p>
      </section>

      <section class="card p-5">
        <button type="button" class="btn-secondary" @click="signOut">
          <AppIcon name="logout" :size="15" />
          Sign out
        </button>
      </section>
    </div>
  </div>
</template>
