---
title: techne
hide:
  - navigation
  - toc
  - footer
---

<div class="hero" markdown>

# τέχνη · techne

**Nine Claude Code skills. One `/plugin` install. Sister-repo hygiene built in.**
{ .hero-subtitle }

<div class="hero-buttons" markdown>

[:octicons-rocket-24: Get Started](getting-started.md){ .md-button .md-button--primary }
[:octicons-list-unordered-24: Browse Skills](skills/index.md){ .md-button }

</div>

</div>

<section class="landing-section landing-section--intro">
  <div class="section-inner">
    <h2 class="section-title">What is techne?</h2>
    <p class="section-lead">A Claude Code plugin shipping nine skills that audit builds, tame CI noise, hunt doc/code drift, and keep sister repos in lockstep. Built for AJ's own multi-repo workflow; usable by anyone who lives in <code>~/.claude/</code>.</p>
  </div>
</section>

<section class="landing-section">
  <div class="section-inner">
    <h2 class="section-title">The Skills</h2>
    <div class="skill-grid">
      <a href="skills/audit/" class="skill-card">
        <div class="skill-name"><code>techne:audit</code></div>
        <p>Runs your repo's <code>make</code> targets in dependency order and reconciles terminal output against <code>logs/dev-*.log</code> archives.</p>
      </a>
      <a href="skills/auto-commit/" class="skill-card">
        <div class="skill-name"><code>techne:auto-commit</code></div>
        <p>Groups working-tree changes into a structured <code>COMMITS.md</code> plan for staged review before anything lands.</p>
      </a>
      <a href="skills/ci-audit/" class="skill-card">
        <div class="skill-name"><code>techne:ci-audit</code></div>
        <p>Audits GitHub Actions runs on the current branch/PR for warnings, failures, and noise. Fixes what's fixable in-repo.</p>
      </a>
      <a href="skills/deslop/" class="skill-card">
        <div class="skill-name"><code>techne:deslop</code></div>
        <p>Scans comments and docstrings for AI-generated slop and proposes tightened rewrites.</p>
      </a>
      <a href="skills/docs-site/" class="skill-card">
        <div class="skill-name"><code>techne:docs-site</code></div>
        <p>Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity.</p>
      </a>
      <a href="skills/docsync/" class="skill-card">
        <div class="skill-name"><code>techne:docsync</code></div>
        <p>Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code.</p>
      </a>
      <a href="skills/reslop/" class="skill-card">
        <div class="skill-name"><code>techne:reslop</code></div>
        <p>Rewrites docstrings grounded in the implementation rather than deleting them outright.</p>
      </a>
      <a href="skills/sisters/" class="skill-card">
        <div class="skill-name"><code>techne:sisters</code></div>
        <p>Cross-repo drift audit across the sister repos listed in <code>~/.claude/techne.toml</code>.</p>
      </a>
      <a href="skills/theoros/" class="skill-card">
        <div class="skill-name"><code>techne:theoros</code></div>
        <p>Starts an observed live dev session: Claude drives the REPL in a named tmux session; you spectate read-only via <code>tmux attach -r</code>.</p>
      </a>
    </div>
  </div>
</section>

<section class="landing-section landing-section--cta" markdown>
  <div class="section-inner" markdown>
    <h2 class="section-title">Install</h2>

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

  <p class="section-lead">Skills become available as <code>techne:&lt;name&gt;</code> and invoke the same way as any other Claude Code skill.</p>

  <div class="hero-buttons" markdown="1">

[:octicons-rocket-24: Get Started](getting-started.md){ .md-button .md-button--primary }
[:octicons-gear-24: Configuration](configuration.md){ .md-button }

  </div>
  </div>
</section>
