#!/usr/bin/env bash
# Install the pinned gitleaks into /usr/local/bin on a Linux x86_64 CI runner, checked against
# its release sha256: the secret guard tests (tests/test_secret_guard.py) run the real scanner.
set -euo pipefail

VERSION=8.30.1
SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb

tmp="${RUNNER_TEMP:-$(mktemp -d)}"
tarball="gitleaks_${VERSION}_linux_x64.tar.gz"
# --retry covers 408, 429, 5xx and timeouts with backoff; a 404 (a wrong pin) fails at once.
# research(2026-11): https://curl.se/docs/manpage.html#--retry
curl -sSfL --retry 5 --retry-connrefused -o "$tmp/$tarball" \
	"https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/$tarball"
echo "${SHA256}  $tmp/$tarball" | sha256sum -c -
sudo tar -xzf "$tmp/$tarball" -C /usr/local/bin gitleaks
gitleaks version
