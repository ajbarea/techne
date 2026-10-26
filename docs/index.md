---
title: techne
description: A plugin marketplace for AI coding agents, for code repos, documents, bibliographies, ideas, Gmail and course sites. Pick the plugin for your job, install it, run its setup skill.
hide:
  - navigation
  - toc
  - footer
---

<div class="hero" markdown>

# τέχνη · techne

**Plugins for AI coding agents, for code repos, documents, bibliographies, ideas, Gmail and course sites. Install the ones you use.**
{ .hero-subtitle }

<div class="hero-install" markdown>

```text
/plugin marketplace add ajbarea/techne
/plugin install <plugin>@techne
```

</div>

<div class="hero-buttons" markdown>

[:octicons-rocket-24: Get Started](getting-started.md){ .md-button .md-button--primary }
[:octicons-list-unordered-24: Pick a plugin](#plugins){ .md-button }

</div>

</div>

<section class="landing-section landing-section--intro" id="plugins">
  <div class="section-inner">
    <h2 class="section-title">Which plugin do you need?</h2>
    <p class="section-lead">techne is a plugin marketplace for AI coding agents. Each plugin is installed on its own, so only the ones you pick put their skill list in the agent's context. Every plugin runs in Claude Code; techne, graphe and dokimasia also run in Codex, Copilot CLI and Antigravity CLI (see <a href="getting-started/#other-agent-clis">Getting Started</a>). After installing, run the plugin's setup skill, <code>/&lt;plugin&gt;:setup</code>: it checks what the plugin needs and prints the install command for anything missing. dokimasia needs only uv and has none; keryx checks itself with <code>keryx status</code>.</p>
    <div class="skill-grid">
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/techne/">techne</a></div>
        <p>Work in a code repo: audit the build, review CI and changes before merge, plan commits, catch up on GitHub threads, check docs against code, keep sister repos in step.</p>
        <code class="plugin-install">/plugin install techne@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/graphe/">graphe</a></div>
        <p>Documents: build and check LaTeX papers, render markdown to PDF, make talk decks, scaffold a paper, review it before submission.</p>
        <code class="plugin-install">/plugin install graphe@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/dokimasia/">dokimasia</a></div>
        <p>Check a bibliography: lint a <code>.bib</code>, verify entries against arXiv and Crossref, confirm every cited key rendered.</p>
        <code class="plugin-install">/plugin install dokimasia@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/heuresis/">heuresis</a></div>
        <p>Triage an idea: search papers, patents, products and your own work, name the closest existing work, file the idea.</p>
        <code class="plugin-install">/plugin install heuresis@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/epistole/">epistole</a></div>
        <p>Gmail across accounts: search, read and draft mail, and send a draft only after you approve it.</p>
        <code class="plugin-install">/plugin install epistole@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/schole/">schole</a></div>
        <p>Brightspace (D2L) course sites, read-only: new announcements and content, what is due, what came due unsubmitted.</p>
        <code class="plugin-install">/plugin install schole@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/phylax/">phylax</a></div>
        <p>Opt-in git guards (no attribution lines, no staged <code>COMMITS.md</code>, main-checkout warning), a model on every subagent call, restart onto an updated Claude Code, and budget mode.</p>
        <code class="plugin-install">/plugin install phylax@techne</code>
      </div>
      <div class="skill-card">
        <div class="skill-name"><a href="plugins/keryx/">keryx</a></div>
        <p>Speaks a short gist of each reply in a local voice.</p>
        <code class="plugin-install">/plugin install keryx@techne</code>
      </div>
    </div>
  </div>
</section>

<section class="landing-section landing-section--cta">
  <div class="section-inner">
    <h2 class="section-title">Next</h2>
    <p class="section-lead">Invoke a skill as <code>/&lt;plugin&gt;:&lt;skill&gt;</code>, or describe the task and let Claude pick one. Every skill has a page that says when to use it and what it changes.</p>
    <div class="hero-buttons hero-buttons--cta">
      <a href="getting-started/" class="md-button md-button--primary">Get Started</a>
      <a href="skills/" class="md-button">Browse Skills</a>
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
