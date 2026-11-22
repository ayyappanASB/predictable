#!/usr/bin/env bash
# Deploy PREDICTABLE to Vercel: the WebAssembly game + the support page + the feedback API.
#   bash tools/build_web.sh && bash tools/deploy_vercel.sh
# The Vercel project link (.vercel/) and secrets never leave dist/deploy/predictable.
set -euo pipefail
cd "$(dirname "$0")/.."
WEB="dist/predictable/build/web"
OUT="dist/deploy/predictable"            # folder name = Vercel project name
[ -f "$WEB/index.html" ] || { echo "run tools/build_web.sh first"; exit 1; }
mkdir -p "$OUT"
rsync -a --delete --exclude ".vercel" --exclude ".env*" --exclude "node_modules" \
  "$WEB/index.html" "$WEB/predictable.apk" "$WEB/predictable.tar.gz" "$WEB/favicon.png" \
  vercel/vercel.json vercel/package.json vercel/package-lock.json vercel/support.html vercel/api \
  "$OUT/"
(cd vercel && node --test tests/ >/dev/null) || { echo "API tests failed - not deploying"; exit 1; }
cd "$OUT" && vercel deploy --prod --yes
