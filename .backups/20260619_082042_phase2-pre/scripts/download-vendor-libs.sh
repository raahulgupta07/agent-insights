#!/usr/bin/env bash
# Download vendored JS libraries for airgapped artifact rendering.
# These libraries are used inside iframe sandboxes and headless browser rendering.
# Run this script during Docker build or local development setup.
set -euo pipefail

LIBS_DIR="${1:-frontend/public/libs}"
mkdir -p "$LIBS_DIR"

echo "Downloading vendored JS libraries to $LIBS_DIR ..."

# Tailwind CSS Play CDN (JIT compiler for runtime Tailwind in artifacts)
curl -sL "https://cdn.tailwindcss.com/3.4.16" \
  -o "$LIBS_DIR/tailwindcss-3.4.16.js"

# React 18 production UMD build
curl -sL "https://unpkg.com/react@18/umd/react.production.min.js" \
  -o "$LIBS_DIR/react-18.production.min.js"

# React 18 development UMD build (used in artifact iframe for readable error messages)
curl -sL "https://unpkg.com/react@18/umd/react.development.js" \
  -o "$LIBS_DIR/react-18.development.js"

# ReactDOM 18 production UMD build
curl -sL "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" \
  -o "$LIBS_DIR/react-dom-18.production.min.js"

# ReactDOM 18 development UMD build
curl -sL "https://unpkg.com/react-dom@18/umd/react-dom.development.js" \
  -o "$LIBS_DIR/react-dom-18.development.js"

# Babel Standalone (JSX transpilation in browser)
# PINNED to 7.x: babel 8 defaults preset-react runtime='automatic', which injects
# `import {jsx} from "react/jsx-runtime"` into the classic <script type="text/babel">,
# throwing "Cannot use import statement outside a module" and blanking the artifact.
# 7.x defaults runtime='classic' -> React.createElement + global React. Do NOT unpin.
curl -sL "https://unpkg.com/@babel/standalone@7.26.4/babel.min.js" \
  -o "$LIBS_DIR/babel-standalone.min.js"

# ECharts 5 (charting library)
curl -sL "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js" \
  -o "$LIBS_DIR/echarts-5.min.js"

echo "Vendored JS libraries downloaded:"
ls -lh "$LIBS_DIR"
