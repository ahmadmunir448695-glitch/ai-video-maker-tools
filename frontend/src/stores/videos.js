import { defineStore } from "pinia";

import { api, uploadVideo } from "@/lib/api";

export const useVideoStore = defineStore("videos", {
  state: () => ({
    items: [],
    loading: false,
    loaded: false,
    /** Live upload state, so the UI can show a real progress bar. */
    upload: { active: false, progress: 0, filename: "", error: null },
    _abortUpload: null,
  }),

  getters: {
    byId: (state) => (id) => state.items.find((item) => item.id === id) || null,
    ready: (state) => state.items.filter((item) => item.status === "ready"),
    count: (state) => state.items.length,
  },

  actions: {
    async load({ force = false } = {}) {
      if (this.loaded && !force) return;
      this.loading = true;
      try {
        const body = await api.get("/videos/?page_size=100");
        this.items = body.results || [];
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },

    async fetchOne(id) {
      const asset = await api.get(`/videos/${id}/`);
      const index = this.items.findIndex((item) => item.id === id);
      if (index === -1) this.items.unshift(asset);
      else this.items[index] = asset;
      return asset;
    },

    /** Upload a file, reporting progress. Resolves with the created asset. */
    async uploadFile(file) {
      this.upload = { active: true, progress: 0, filename: file.name, error: null };

      const { promise, abort } = uploadVideo(file, {
        onProgress: (percent) => {
          // Hold at 99 while the server probes the file: the bytes are sent,
          // but the asset is not usable until FFprobe has read it.
          this.upload.progress = Math.min(percent, 99);
        },
      });
      this._abortUpload = abort;

      try {
        const asset = await promise;
        this.upload.progress = 100;
        this.items.unshift(asset);
        return asset;
      } catch (error) {
        this.upload.error = error.message;
        throw error;
      } finally {
        this.upload.active = false;
        this._abortUpload = null;
      }
    },

    cancelUpload() {
      this._abortUpload?.();
    },

    clearUploadError() {
      this.upload.error = null;
    },

    async remove(id) {
      await api.delete(`/videos/${id}/`);
      this.items = this.items.filter((item) => item.id !== id);
    },

    async downloadUrl(id) {
      return api.get(`/videos/${id}/download/`);
    },
  },
});
