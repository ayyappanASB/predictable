#!/usr/bin/env bash
# Build the browser version with pygbag (Python -> WebAssembly).
# Only the files the game needs are staged, so the download stays small.
#   bash tools/build_web.sh          -> dist/predictable/build/web/  (index.html + predictable.apk)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

STAGE="dist/predictable"
mkdir -p "$STAGE"
rsync -a --delete --exclude "__pycache__" --exclude "build" main.py game assets "$STAGE/"

"$PY" -m pygbag --build --title "PREDICTABLE" --ume_block 0 "$STAGE"

# Re-theme pygbag's default page (grey / light-blue loader) to match the game.
"$PY" - "$STAGE/build/web/index.html" <<'EOF'
import sys
path = sys.argv[1]
html = open(path, encoding="utf-8").read()
for old, new in (
    ('platform.document.body.style.background = "#7f7f7f"',
     'platform.document.body.style.background = "#070a14"'),
    ("background-color:powderblue;",
     "background-color:#070a14; overscroll-behavior: none; touch-action: none;"
     " user-select: none; -webkit-user-select: none; -webkit-tap-highlight-color: transparent;"),
    # phones: one proper viewport, no pinch-zoom, swipes go to the game not the page
    ('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
     '    <meta name="viewport" content="height=device-height, initial-scale=1.0">',
     '    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0,'
     ' user-scalable=no, viewport-fit=cover">\n'
     '    <meta name="mobile-web-app-capable" content="yes">\n'
     '    <meta name="apple-mobile-web-app-capable" content="yes">\n'
     '    <meta name="theme-color" content="#070a14">'),
    ("        canvas.emscripten {\n            border: 0px none;",
     "        canvas.emscripten {\n            touch-action: none;\n            outline: none;\n"
     "            border: 0px none;"),
    ("background: green;\n            color: blue;",
     "background: #0f1528;\n            color: #40e2ff;\n            border: 1px solid #22304e;\n"
     "            border-radius: 12px;\n            letter-spacing: 2px;"),
):
    if old not in html:
        sys.exit(f"theme patch not applied, pattern missing: {old[:40]}")
    html = html.replace(old, new)
# Support pop-up: the game calls window.openSupport(ctx) (via pygbag's JS bridge) and the
# feedback form (support page on Vercel) opens in an iframe over the canvas. Key presses inside
# the iframe never reach the game, so typing works on every device.
SUPPORT = """
<style>
  #support-pop { position: fixed; inset: 0; z-index: 9999; display: none; place-items: center;
    background: rgba(3, 5, 11, .82); padding: 12px; }
  #support-pop.open { display: grid; }
  #support-pop iframe { width: min(560px, 100%); height: min(720px, 96vh); border: 0;
    background: transparent; color-scheme: normal; }
</style>
<div id="support-pop" role="dialog" aria-modal="true" aria-label="Support and feedback"></div>
<script>
  window.openSupport = function (ctx) {
    var pop = document.getElementById("support-pop");
    pop.innerHTML = "";
    var frame = document.createElement("iframe");
    frame.title = "Support and feedback form";
    frame.src = "https://predictable-pi.vercel.app/support?embed=1&ctx=" + encodeURIComponent(ctx || "{}");
    pop.appendChild(frame);
    pop.classList.add("open");
    setTimeout(function () { frame.focus(); }, 50);
  };
  window.closeSupport = function () {
    var pop = document.getElementById("support-pop");
    pop.classList.remove("open");
    pop.innerHTML = "";
    var canvas = document.getElementById("canvas");
    if (canvas) canvas.focus();
  };
  window.addEventListener("message", function (e) {
    if (e.origin === "https://predictable-pi.vercel.app" && e.data && e.data.type === "predictable-support-close") {
      window.closeSupport();
    }
  });
  document.getElementById("support-pop").addEventListener("click", function (e) {
    if (e.target.id === "support-pop") window.closeSupport();   // click outside the form closes it
  });
</script>
"""
if "</body>" not in html:
    sys.exit("support patch not applied: </body> missing")
html = html.replace("</body>", SUPPORT + "</body>", 1)
open(path, "w", encoding="utf-8").write(html)
print("page theme + support pop-up applied")
EOF

# Safety check: every game file must be inside the web package.
"$PY" - "$STAGE" <<'EOF'
import os, sys, tarfile
stage = sys.argv[1]
expected = {os.path.relpath(os.path.join(d, f), stage)
            for d, _, files in os.walk(stage) if "build" not in d.split(os.sep)
            for f in files if f.endswith((".py", ".ogg"))}
with tarfile.open(os.path.join(stage, "build", "web", "predictable.tar.gz")) as tar:
    packed = {n.split("assets/", 1)[1] for n in tar.getnames() if "assets/" in n}
missing = sorted(expected - packed)
if missing:
    sys.exit(f"web package is missing files: {missing}")
print(f"package check passed: {len(expected)} files")
EOF
echo "Web build ready: $STAGE/build/web"
