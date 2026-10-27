#!/bin/bash
set -euo pipefail
git init -q . && git config user.email t@t && git config user.name t
mkdir -p src
cat > Cargo.toml <<'TOML'
[package]
name = "gauge"
version = "0.4.0"
edition = "2021"

[dependencies]
tauri = "2"
TOML
cat > src/main.rs <<'RS'
mod bar;
mod wall;

fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("wall") => wall::show(),
        _ => bar::show(),
    }
}
RS
cat > src/bar.rs <<'RS'
/// The always-on-top bar: session and weekly usage limits.
pub fn show() {}
RS
cat > src/wall.rs <<'RS'
/// The fleet wall: one card per running Claude Code session, the ones waiting on you first.
pub fn show() {}
RS
cat > README.md <<'MD'
# gauge

Your Claude Code usage limit, always on screen.

## The bar

`gauge` opens a thin always-on-top bar with your session and weekly limits.

## The wall

`gauge wall` opens the fleet wall: a card per running Claude Code session, the ones
waiting on you first.
MD
git add -A && git commit -qm init
