#!/usr/bin/env bash
# Print the path of the pinned hyperfine, downloading its release binary once into the user cache
# and checking it against the release's sha256 before use. Linux on x86_64 or aarch64 only (the
# static musl builds); elsewhere it says so and exits 1.
set -euo pipefail

VERSION=2.0.0
case "$(uname -s)-$(uname -m)" in
Linux-x86_64)
	target=x86_64-unknown-linux-musl
	sha=38e59087bd65520930a13cf513d8a493b7043741e8ad62349a8a9929eb61bc5c
	;;
Linux-aarch64)
	target=aarch64-unknown-linux-musl
	sha=f0591c2cb8f66f2d2624d23979cf96dc99a67cb935f9925c82b9a4e3ffe5b2e1
	;;
*)
	echo "install_hyperfine: no pinned hyperfine build for $(uname -s) $(uname -m); install hyperfine $VERSION yourself and set HYPERFINE" >&2
	exit 1
	;;
esac

dir="${XDG_CACHE_HOME:-$HOME/.cache}/techne/hyperfine-$VERSION-$target"
bin="$dir/hyperfine"
if [ ! -x "$bin" ]; then
	name="hyperfine-v$VERSION-$target"
	tmp="$(mktemp -d)"
	trap 'rm -rf -- "${tmp:?}"' EXIT
	curl --fail --silent --show-error --location --retry 3 \
		--output "$tmp/$name.tar.gz" \
		"https://github.com/sharkdp/hyperfine/releases/download/v$VERSION/$name.tar.gz"
	echo "$sha  $tmp/$name.tar.gz" | sha256sum --check --quiet >&2
	tar -xzf "$tmp/$name.tar.gz" -C "$tmp"
	mkdir -p "$dir"
	install -m 0755 "$tmp/$name/hyperfine" "$bin"
fi
echo "$bin"
