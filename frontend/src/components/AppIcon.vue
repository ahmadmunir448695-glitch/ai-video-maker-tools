<script setup>
/** Inline SVG icons, so there is no icon-font request and they inherit colour. */
const paths = {
  dashboard: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm9 0h7V11h-7v9Zm0-11h7V4h-7v5Z",
  upload: "M12 16V5m0 0 4 4m-4-4-4 4M5 19h14",
  film: "M4 5h16v14H4zM9 5v14M15 5v14M4 9h5M4 15h5M15 9h5M15 15h5",
  scissors: "M8 6a2 2 0 1 1-2 2 2 2 0 0 1 2-2Zm0 10a2 2 0 1 1-2 2 2 2 0 0 1 2-2Zm1.5-7.5L20 19M9.5 15.5 20 5",
  download: "M12 4v11m0 0 4-4m-4 4-4-4M5 20h14",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7.6 7.6 0 0 0-2.1 1.2l-2.3-1-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.5l-2 1.5 2 3.4 2.3-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.6 7.6 0 0 0 2.1-1.2l2.3 1 2-3.4-2-1.5c.06-.4.1-.8.1-1.2Z",
  check: "M5 13l4 4L19 7",
  x: "M6 6l12 12M18 6 6 18",
  alert: "M12 9v4m0 4h.01M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0Z",
  clock: "M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
  retry: "M4 10a8 8 0 0 1 14-4m2-3v6h-6M20 14a8 8 0 0 1-14 4m-2 3v-6h6",
  play: "M7 4v16l13-8z",
  pause: "M8 5v14M16 5v14",
  logout: "M15 17l5-5-5-5m5 5H9M12 19H5V5h7",
  plus: "M12 5v14M5 12h14",
  spinner: "M12 3a9 9 0 1 0 9 9",
};

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  filled: { type: Boolean, default: false },
});
</script>

<template>
  <svg
    :width="props.size"
    :height="props.size"
    viewBox="0 0 24 24"
    :fill="props.filled ? 'currentColor' : 'none'"
    :stroke="props.filled ? 'none' : 'currentColor'"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[props.name] || ''" />
  </svg>
</template>
