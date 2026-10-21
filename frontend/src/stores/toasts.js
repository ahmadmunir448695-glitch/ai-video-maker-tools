import { defineStore } from "pinia";

let nextId = 1;

/** Transient notifications: progress, completion and errors. */
export const useToastStore = defineStore("toasts", {
  state: () => ({ items: [] }),

  actions: {
    push({ message, kind = "info", timeout = 5000 }) {
      const id = nextId++;
      this.items.push({ id, message, kind });
      if (timeout > 0) setTimeout(() => this.dismiss(id), timeout);
      return id;
    },

    success(message) {
      return this.push({ message, kind: "success" });
    },

    error(message) {
      // Errors stay longer: they usually need reading, and sometimes acting on.
      return this.push({ message, kind: "error", timeout: 9000 });
    },

    info(message) {
      return this.push({ message, kind: "info" });
    },

    dismiss(id) {
      this.items = this.items.filter((item) => item.id !== id);
    },
  },
});
