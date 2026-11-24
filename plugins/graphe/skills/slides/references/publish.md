<!-- budget: 560 words -->
# Publishing a web deck

A web deck is published with GitHub Pages, and the link is the handout.
Publish only what is cleared for release: a Pages site is public even when its
repo is private, and a private repo needs a paid plan for Pages at all.

**Keep every talk in one talks repo.** A repository has one Pages site, but the
site serves folders, so one public repo with a folder per talk gives each talk
its own address (`<owner>.github.io/talks/<talk>/`), and every future deck has
the same home. Research repos stay where they are and supply the figures: each
talk's build reads them. [ajbarea/talks](https://github.com/ajbarea/talks) is
the worked example: reveal.js shared at `vendor/reveal/`, a `scripts/site.py`
that lays out every folder holding an `index.html` and writes an index page from
each talk's `<title>` and description, and one workflow that checks every talk
on each pull request and daily, and publishes on `main`.

To add a talk there:

1. Copy the starter into a new folder named for the talk; the folder name is its
   address. Point its `vendor/reveal/` links at `../vendor/reveal/` and delete
   its own copy.
2. Give the page a `<title>` and a `<meta name="description">`; the index lists
   the talk by them.
3. If its figures come from research artifacts, add a `figures.py` that writes
   them into `data/` and fails with `--check` when they are stale.
4. Open a pull request; merging it publishes the talk. Put its link on the
   closing slide.

**One deck in its own repo**, when a talk must stay apart from the rest:

1. Commit the deck folder to the repo.
2. Copy the skill's `templates/pages.yml` to `.github/workflows/deck.yml`
   and replace `DECK_DIR` with the deck folder's path.
3. Set the Pages source to GitHub Actions:
   `gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow`
   (or `-X PUT` if Pages already exists). In a repo that already publishes a
   site (docs, say), this replaces it.
4. Push. The deploy job prints the URL; put it on the closing slide.

The template's actions are pinned to commit SHAs, and techne's guard keeps them
equal to the pins techne's own workflows use.

