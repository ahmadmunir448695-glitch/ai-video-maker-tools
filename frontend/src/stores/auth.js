import { defineStore } from "pinia";

import { api, onUnauthenticated, refreshAccessToken, setAccessToken } from "@/lib/api";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null,
    usage: null,
    /** False until the first refresh attempt settles, so routing can wait. */
    ready: false,
    busy: false,
  }),

  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    displayName: (state) => state.user?.name || state.user?.email || "",
    storageUsedRatio: (state) => {
      if (!state.usage?.storage_bytes_limit) return 0;
      return Math.min(1, state.usage.storage_bytes_used / state.usage.storage_bytes_limit);
    },
  },

  actions: {
    /**
     * Work out whether there is already a session, using the refresh cookie.
     * Called once at startup, before the first route is resolved.
     */
    async initialise() {
      onUnauthenticated(() => this.clear());
      try {
        const body = await refreshAccessToken();
        this.user = body.user;
        await this.loadProfile();
      } catch {
        this.clear();
      } finally {
        this.ready = true;
      }
    },

    async register({ email, password, displayName }) {
      this.busy = true;
      try {
        const body = await api.post("/auth/register", {
          email,
          password,
          display_name: displayName || "",
        });
        setAccessToken(body.access);
        this.user = body.user;
        await this.loadProfile();
      } finally {
        this.busy = false;
      }
    },

    async login({ email, password }) {
      this.busy = true;
      try {
        const body = await api.post("/auth/login", { email, password });
        setAccessToken(body.access);
        this.user = body.user;
        await this.loadProfile();
      } finally {
        this.busy = false;
      }
    },

    async logout() {
      try {
        await api.post("/auth/logout");
      } finally {
        this.clear();
      }
    },

    async loadProfile() {
      const body = await api.get("/auth/me");
      this.user = body.user;
      this.usage = body.usage;
    },

    async updateDisplayName(displayName) {
      const body = await api.patch("/auth/me", { display_name: displayName });
      this.user = body.user;
    },

    async changePassword({ currentPassword, newPassword }) {
      const body = await api.post("/auth/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setAccessToken(body.access);
      this.user = body.user;
    },

    clear() {
      setAccessToken(null);
      this.user = null;
      this.usage = null;
    },
  },
});
