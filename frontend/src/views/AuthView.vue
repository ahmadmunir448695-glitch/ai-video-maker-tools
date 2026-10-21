<script setup>
import { computed, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const mode = ref("sign-in");
const form = reactive({ email: "", password: "", displayName: "" });
const error = ref("");
const fieldErrors = ref({});

const isRegister = computed(() => mode.value === "register");
const heading = computed(() => (isRegister.value ? "Create your account" : "Welcome back"));
const submitLabel = computed(() => (isRegister.value ? "Create account" : "Sign in"));

function switchMode() {
  mode.value = isRegister.value ? "sign-in" : "register";
  error.value = "";
  fieldErrors.value = {};
}

async function submit() {
  error.value = "";
  fieldErrors.value = {};

  try {
    if (isRegister.value) {
      await auth.register({
        email: form.email,
        password: form.password,
        displayName: form.displayName,
      });
    } else {
      await auth.login({ email: form.email, password: form.password });
    }
    router.replace(route.query.next || { name: "dashboard" });
  } catch (err) {
    error.value = err.message;
    // The server reports per-field problems (e.g. every failed password rule),
    // so show them against the field rather than as one vague sentence.
    if (err.fields) {
      fieldErrors.value = {
        email: err.fieldError("email"),
        password: err.fieldError("password"),
      };
    }
  }
}
</script>

<template>
  <div class="flex min-h-dvh items-center justify-center px-4 py-10">
    <div class="w-full max-w-md">
      <div class="mb-8 flex items-center justify-center gap-2.5">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-brand-500 text-white">
          <AppIcon name="film" :size="20" />
        </span>
        <span class="text-xl font-bold tracking-tight">Reelcraft</span>
      </div>

      <div class="card p-6 sm:p-8">
        <h1 class="text-xl font-bold">{{ heading }}</h1>
        <p class="mt-1 text-sm text-mist-500">
          Trim a video, change its speed, make it vertical, and export it.
        </p>

        <form class="mt-6 space-y-4" novalidate @submit.prevent="submit">
          <div v-if="isRegister">
            <label class="label" for="displayName">Your name <span class="text-mist-500">(optional)</span></label>
            <input
              id="displayName"
              v-model.trim="form.displayName"
              class="input"
              autocomplete="name"
              placeholder="Alex"
            />
          </div>

          <div>
            <label class="label" for="email">Email</label>
            <input
              id="email"
              v-model.trim="form.email"
              class="input"
              type="email"
              required
              autocomplete="email"
              placeholder="you@example.com"
              :aria-invalid="Boolean(fieldErrors.email)"
            />
            <p v-if="fieldErrors.email" class="field-error">{{ fieldErrors.email }}</p>
          </div>

          <div>
            <label class="label" for="password">Password</label>
            <input
              id="password"
              v-model="form.password"
              class="input"
              type="password"
              required
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              placeholder="••••••••••"
              :aria-invalid="Boolean(fieldErrors.password)"
            />
            <p v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</p>
            <p v-else-if="isRegister" class="mt-1.5 text-xs text-mist-500">
              At least 10 characters. Avoid common passwords.
            </p>
          </div>

          <p
            v-if="error && !fieldErrors.email && !fieldErrors.password"
            class="rounded-xl border border-rose-400/40 bg-rose-400/10 px-3.5 py-2.5 text-sm text-rose-400"
            role="alert"
          >
            {{ error }}
          </p>

          <button type="submit" class="btn-primary w-full" :disabled="auth.busy">
            <AppIcon v-if="auth.busy" name="spinner" :size="16" class="animate-spin" />
            {{ auth.busy ? "Please wait…" : submitLabel }}
          </button>
        </form>

        <p class="mt-6 text-center text-sm text-mist-500">
          {{ isRegister ? "Already have an account?" : "New here?" }}
          <button type="button" class="font-semibold text-brand-300 hover:underline" @click="switchMode">
            {{ isRegister ? "Sign in" : "Create an account" }}
          </button>
        </p>
      </div>
    </div>
  </div>
</template>
