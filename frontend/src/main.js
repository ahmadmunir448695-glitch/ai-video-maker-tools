import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";
import "./assets/main.css";

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);

// Resolve whether there is an existing session (via the HttpOnly refresh
// cookie) before the router runs, so a reload does not flash the sign-in page.
const auth = useAuthStore(pinia);
auth.initialise().finally(() => {
  app.use(router);
  app.mount("#app");
});
