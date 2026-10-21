import { defineStore } from "pinia";

import { api } from "@/lib/api";

/** Statuses that mean a job still has work to do. */
const ACTIVE = ["pending", "queued", "processing"];

/** How often to re-check while anything is rendering. */
const POLL_INTERVAL_MS = 2500;

export const useExportStore = defineStore("exports", {
  state: () => ({
    items: [],
    loading: false,
    loaded: false,
    options: null,
    /** Set when a create request returned an existing export instead of rendering. */
    lastReused: false,
    _pollTimer: null,
  }),

  getters: {
    byId: (state) => (id) => state.items.find((item) => item.id === id) || null,
    active: (state) => state.items.filter((item) => ACTIVE.includes(item.status)),
    finished: (state) => state.items.filter((item) => item.status === "succeeded"),
    failed: (state) => state.items.filter((item) => ["failed", "cancelled"].includes(item.status)),
    hasActive() {
      return this.active.length > 0;
    },
    forSource: (state) => (sourceId) => state.items.filter((item) => item.source_id === sourceId),
  },

  actions: {
    async load({ force = false } = {}) {
      if (this.loaded && !force) return;
      this.loading = true;
      try {
        const body = await api.get("/exports/?page_size=100");
        this.items = body.results || [];
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },

    async loadOptions() {
      if (this.options) return this.options;
      this.options = await api.get("/editor/options");
      return this.options;
    },

    /** Ask the server what an edit would produce, without rendering it. */
    async preview({ sourceId, spec }) {
      return api.post("/editor/preview", { source: sourceId, spec });
    },

    async create({ sourceId, spec, title = "" }) {
      const job = await api.post("/exports/", { source: sourceId, spec, title });
      // The server returns an existing export for an identical edit rather than
      // rendering it again, so an id we already hold is an update, not a new row.
      const index = this.items.findIndex((item) => item.id === job.id);
      this.lastReused = index !== -1 || job.status === "succeeded";
      if (index === -1) this.items.unshift(job);
      else this.items[index] = job;
      this.startPolling();
      return job;
    },

    async refreshOne(id) {
      try {
        const job = await api.get(`/exports/${id}/`);
        const index = this.items.findIndex((item) => item.id === id);
        if (index !== -1) this.items[index] = job;
        return job;
      } catch (error) {
        // A job deleted elsewhere should disappear rather than wedge the poll.
        if (error.status === 404) {
          this.items = this.items.filter((item) => item.id !== id);
          return null;
        }
        throw error;
      }
    },

    async cancel(id) {
      const job = await api.post(`/exports/${id}/cancel/`);
      this._replace(job);
      return job;
    },

    async retry(id) {
      const job = await api.post(`/exports/${id}/retry/`);
      this._replace(job);
      this.startPolling();
      return job;
    },

    async remove(id) {
      await api.delete(`/exports/${id}/`);
      this.items = this.items.filter((item) => item.id !== id);
    },

    async downloadUrl(id) {
      return api.get(`/exports/${id}/download/`);
    },

    /** Poll only while something is actually rendering, then stop. */
    startPolling() {
      if (this._pollTimer) return;
      this._pollTimer = setInterval(async () => {
        const running = this.active;
        if (running.length === 0) {
          this.stopPolling();
          return;
        }
        await Promise.allSettled(running.map((job) => this.refreshOne(job.id)));
      }, POLL_INTERVAL_MS);
    },

    stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    },

    _replace(job) {
      const index = this.items.findIndex((item) => item.id === job.id);
      if (index !== -1) this.items[index] = job;
      else this.items.unshift(job);
    },

    reset() {
      this.stopPolling();
      this.items = [];
      this.loaded = false;
    },
  },
});
