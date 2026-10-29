#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > README.md <<'EOF_FILE'
# plugin

Run `bash install.sh <dest>` to install.
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > install.sh <<'EOF_FILE'
#!/bin/bash
# Install the plugin folder next to this script into DEST, replacing any older copy.
set -euo pipefail
src="$(cd "$(dirname "$0")" && pwd)/plugin"
dest="$1"
rm -rf "$dest"
mkdir -p "$dest"
cp -r "$src"/. "$dest"/
echo "installed to $dest"
EOF_FILE
mkdir -p plugin
cat > plugin/hello.txt <<'EOF_FILE'
hi
EOF_FILE
git add -A && git commit -qm "install: copy the plugin into its destination"
