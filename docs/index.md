---
title: techne
hide:
  - navigation
  - toc
  - footer
---

<div class="hero" markdown>

# τέχνη · techne

**Opinionated Claude Code skills for repo hygiene. One `/plugin` install.**
{ .hero-subtitle }

<div class="hero-buttons" markdown>

[:octicons-rocket-24: Get Started](getting-started.md){ .md-button .md-button--primary }
[:octicons-list-unordered-24: Browse Skills](skills/index.md){ .md-button }

</div>

</div>

<section class="landing-section landing-section--intro">
  <div class="section-inner">
    <h2 class="section-title">What is techne?</h2>
    <p class="section-lead">A Claude Code plugin for repo hygiene: audit builds, tame CI noise, hunt doc/code drift, and keep linked repos in lockstep. Opinionated kit; adopt the conventions and the skills work for any developer.</p>
  </div>
</section>

<section class="landing-section">
  <div class="section-inner">
    <h2 class="section-title">The Skills</h2>
    <div class="skill-grid">
      <a href="skills/audit/" class="skill-card">
        <div class="skill-name"><code>/techne:audit</code></div>
        <p>Runs your repo's <code>make</code> targets in dependency order and reconciles terminal output against <code>logs/dev-*.log</code> archives.</p>
      </a>
      <a href="skills/auto-commit/" class="skill-card">
        <div class="skill-name"><code>/techne:auto-commit</code></div>
        <p>Groups working-tree changes into a structured <code>COMMITS.md</code> plan for staged review before anything lands.</p>
      </a>
      <a href="skills/catchup/" class="skill-card">
        <div class="skill-name"><code>/techne:catchup</code></div>
        <p>Reads every comment, review, and state change on a repo since you last participated, then reports who is blocked on whom.</p>
      </a>
      <a href="skills/ci-audit/" class="skill-card">
        <div class="skill-name"><code>/techne:ci-audit</code></div>
        <p>Audits GitHub Actions runs on the current branch/PR for warnings, failures, and noise. Fixes what's fixable in-repo.</p>
      </a>
      <a href="skills/deslop/" class="skill-card">
        <div class="skill-name"><code>/techne:deslop</code></div>
        <p>Scans comments and docstrings for AI-generated slop and proposes tightened rewrites.</p>
      </a>
      <a href="skills/docs-site/" class="skill-card">
        <div class="skill-name"><code>/techne:docs-site</code></div>
        <p>Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity.</p>
      </a>
      <a href="skills/docsync/" class="skill-card">
        <div class="skill-name"><code>/techne:docsync</code></div>
        <p>Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code.</p>
      </a>
      <a href="skills/elenchus/" class="skill-card">
        <div class="skill-name"><code>/techne:elenchus</code></div>
        <p>Adversarial pre-merge review: reproduces the load-bearing claim, traces every consumer, and walks a bug-class rubric.</p>
      </a>
      <a href="skills/latex/" class="skill-card">
        <div class="skill-name"><code>/techne:latex</code></div>
        <p>Builds a LaTeX document and gates it on its log, its PDF, and the assignment it answers.</p>
      </a>
      <a href="skills/paper/" class="skill-card">
        <div class="skill-name"><code>/techne:paper</code></div>
        <p>Scaffolds a new paper directory in a papers-style monorepo so it builds on day one.</p>
      </a>
      <a href="skills/paper-review/" class="skill-card">
        <div class="skill-name"><code>/techne:paper-review</code></div>
        <p>Pre-submission novelty and reviewer pass, with every verdict grounded in retrieved prior work.</p>
      </a>
      <a href="skills/pdf/" class="skill-card">
        <div class="skill-name"><code>/techne:pdf</code></div>
        <p>Renders markdown to print-quality PDFs through a Typst template, then verifies fonts and content against the source.</p>
      </a>
      <a href="skills/research-grounded/" class="skill-card">
        <div class="skill-name"><code>/techne:research-grounded</code></div>
        <p>Flags design decisions in <code>IMPL.md</code> / <code>ROADMAP.md</code> that lack <code>research(YYYY-MM)</code> provenance, then web-searches to ground them.</p>
      </a>
      <a href="skills/reslop/" class="skill-card">
        <div class="skill-name"><code>/techne:reslop</code></div>
        <p>Rewrites docstrings grounded in the implementation rather than deleting them outright.</p>
      </a>
      <a href="skills/sisters/" class="skill-card">
        <div class="skill-name"><code>/techne:sisters</code></div>
        <p>Cross-repo drift audit across the sister repos listed in <code>~/.claude/techne.toml</code>.</p>
      </a>
      <a href="skills/slides/" class="skill-card">
        <div class="skill-name"><code>/techne:slides</code></div>
        <p>Gates a talk deck before it is presented: real slide titles, contrast, alt text, stray figures; renders it through the app that will show it.</p>
      </a>
      <a href="skills/theoros/" class="skill-card">
        <div class="skill-name"><code>/techne:theoros</code></div>
        <p>Starts an observed live dev session: Claude drives the REPL in a named tmux session; you spectate read-only via <code>tmux attach -r</code>.</p>
      </a>
    </div>
  </div>
</section>

<section class="landing-section landing-section--cta">
  <div class="section-inner">
    <h2 class="section-title">Install</h2>
    <div class="highlight">
      <pre><code>/plugin marketplace add ajbarea/techne
/plugin install techne@techne</code></pre>
    </div>
    <p class="section-lead">Install once, then invoke a skill as <code>/techne:&lt;name&gt;</code> or describe the task and let Claude pick it.</p>
    <div class="hero-buttons hero-buttons--cta">
      <a href="getting-started/" class="md-button md-button--primary">Get Started</a>
      <a href="configuration/" class="md-button">Configuration</a>
    </div>
  </div>
</section>

<footer class="landing-footer">
  <span>2026 <img src="assets/brand.png" alt="" aria-hidden="true" class="brand-mark"> AJ Barea</span>
  <a href="https://github.com/ajbarea/techne" aria-label="GitHub">
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
  </a>
</footer>
