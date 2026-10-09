// Every figure and every related-work entry the deck shows. Slides read these through
// data-value, data-dots and data-source; nothing on a slide is typed by hand. In a repo with
// results, generate this file from the artifacts in the build instead of editing it.
// A .js file rather than JSON, so the deck opens from file:// with no server.
window.DECK_DATA = {
  results: {
    // [Share of cases that fail, 0 to 1. From <artifact path>.]
    failShare: 0.56,
    // [Raw counts behind it, for the backup table.]
    failed: 987,
    total: 1761,
  },
  related: {
    axes: {
      x: { label: "[When it looks]", levels: ["[before]", "[during]", "[after]"] },
      y: { label: "[What it reads]", levels: ["[outputs]", "[internal state]", "[weights]"] },
    },
    works: [
      {
        id: "a2023",
        label: "[Author 2023]",
        year: 2023,
        group: "[family one]",
        x: "[before]",
        y: "[outputs]",
        oneLine: "[What it does, in one plain sentence.]",
        differs: "[It predicts before the change; ours checks after it.]",
      },
      {
        id: "b2024",
        label: "[Author 2024]",
        year: 2024,
        group: "[family one]",
        x: "[during]",
        y: "[weights]",
        oneLine: "[What it does, in one plain sentence.]",
        differs: "[It needs the training gradients; ours does not.]",
      },
      {
        id: "c2025",
        label: "[Author 2025]",
        year: 2025,
        group: "[family two]",
        x: "[after]",
        y: "[outputs]",
        oneLine: "[What it does, in one plain sentence.]",
        differs: "[It reads only answers; ours reads the inside.]",
      },
      {
        id: "ours",
        label: "[Ours]",
        year: 2026,
        group: "[family two]",
        x: "[after]",
        y: "[internal state]",
        oneLine: "[What ours does, in one plain sentence.]",
        ours: true,
      },
    ],
  },
};
