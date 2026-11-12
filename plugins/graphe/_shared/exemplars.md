# Exemplars: the bar for research communication

The pages, decks and videos that set AJ's quality bar. Read this before building or reviewing a talk deck, a paper's web page, a playground or a research video, and compare the draft against each exemplar side by side. "Like X" means X's level of care, never its assets. Update this file, not the skills.

## e-means (Meta FAIR, 2026)

https://e-means.github.io/ (AJ, 2026-11-12: "this is the kinda stuff I want to aim for when I constantly repeat that we are aiming for highest quality and SOTA user experiences").

**The principle AJ liked most:** every visitor picks their own way in. They can **watch** the video, **play** with the playground or **read** the blog and paper. Each stands alone, and each links to the other two.

| Part | What sets the bar |
|---|---|
| Blog hero | The argument is an animation. The two methods race side by side next to a live loss plot, with play and a scrubber. The result shows before any prose. |
| Claim figures | Each claim gets a small scrubbable toy. Labels sit inside the figure, and the time axis stretches around the key moment. The caption gives the toy's real many-seed number (26% against 3.5% stuck, over 200 starts). |
| Playground (its own page) | The real method trains in the browser: 100k points, 500 clusters, 25 dataset shapes, a seed, per-method epochs, play speed, CPU timings, a scrubber, train against held-out test loss. |
| Results map | Every configuration (234 over 16 datasets) as zoomable, pannable small multiples. Hover reads a point. Nothing is a pick. |
| Video | 83 s at 1920x1080 and 60 fps, with no narration. All meaning is on-screen text, so it works muted in a feed. The story: race, headline number, why each step is cheaper, lower loss, mechanism, the baseline's failure, results grid, one number (12.6x median over 24 datasets), four lines of code, authors. |
| Links row | [Paper] [Code] [Cite] [Coauthors] under the title; tabs for Blog, Playground, Video, Paper, Code and Release. |
| Phone | The header restacks, with no horizontal scroll at 390 px. |
| Craft | IBM Plex Sans with a mono for UI labels, KaTeX for math, reduced-motion CSS, one restrained red and blue pair throughout. |

**Gaps to beat:** the video has no captions track (only burned-in text), there is no dark mode, and the favicon is missing.

## Pharos explorer (ours, 2026)

https://ajbarea.github.io/pharos/explorer/ is a research tool built as its own app, not a slide. AJ named it as the model for taking a talk's live lab out of the deck. Patterns to reuse:

- A top bar of tabs, one per view.
- The whole state in the URL (`#tab=corpus&seed=7`), so any view can be shared exactly.
- A seed picker, data downloads, and a visible "Offline build" label.
- Nothing reimplements the research code. Every value is frozen from the same functions the real tool runs (`scripts/build_static_explorer.py`), and the page says which seeds work.

## Rules these exemplars set

- **Web first.** The website gets the full web platform: Workers, live many-seed runs, rich motion. A downloaded copy or a PDF only needs a clean static print (AJ, 2026-11-12: "learning is fun!").
- **A toy is honest.** It shows the mechanism and carries its own many-draw number next to the paper's. A seed picked to make a point is labeled as picked.
- **Pace for humans.** Motion slow enough to follow, with pause, step and replay for the presenter.
