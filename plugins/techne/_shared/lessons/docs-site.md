<!-- budget: 246 words -->
# Lessons for docs sites

Read with `common.md`. `SKILL.md` and `references/polish.md` hold the site rules; these are the lessons they do not carry on their own.

## Reference to beat

- [keryx](https://ajbarea.github.io/keryx/), for a hero that holds at 1920 wide and a clear first page.
- Before calling a site done, open it beside the reference at 1920 wide and name one way it is better and one way it is worse.

### judge-at-1920: Judge a site at 1920 wide

- **Rule:** Run `visual_qa.py` and look at the wide capture, since a layout that passes at 1280 can break at 1920.
- **Why:** A hero passed at 1280 and 390 wide and broke at 1920.
- **Since:** 2026-10-08
- **Check:** guidance: the script captures 1920 wide; a person reads the capture.


### project-pages-root-link: A project site's root link keeps its base path

- **Rule:** Link the home page with the site's base URL, never a bare `/`, which leaves the project path on a GitHub Pages site.
- **Why:** A bare root link bounces a visitor to the owner's user site.
- **Since:** 2026-05-26
- **Check:** guidance: what a link should resolve to depends on the site's configured root.

## Retired
