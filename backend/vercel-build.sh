#!/bin/sh
# Vercel build step ([tool.vercel.scripts] in pyproject.toml): compile the React app into
# backend/static, the directory app.frontend() serves; Vercel promotes it to its CDN.
# Needs "Include files outside the root directory in the Build Step" (Vercel default) because the
# project's Root Directory is backend/.
set -eu
cd "$(dirname "$0")/../frontend"
npm ci
npm run build
rm -rf ../backend/static
cp -r dist ../backend/static
