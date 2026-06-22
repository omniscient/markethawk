FROM node:26-alpine@sha256:a2dc166a387cc6ca1e62d0c8e265e49ca985d6e60abc9fe6e6c3d6ce8e63f606

# Upgrade npm to 11.x. node:22-alpine bundles npm 10.9.8, whose vendored
# picomatch 4.0.3 carries a HIGH ReDoS (CVE-2026-33671); npm 11 drops that
# bundled dependency entirely, clearing the Trivy image gate.
RUN npm install -g npm@11.17.0

WORKDIR /app

COPY package*.json ./

# npm ci (not npm install) — install the exact locked versions so the image is
# reproducible and matches what was security-scanned. npm install would resolve
# newest-in-range at build time, drifting the CVE surface between builds.
#
# Clean the npm cache in the same layer. `npm ci` leaves resolved-but-overridden
# tarballs in /root/.npm/_cacache — e.g. undici 6.26.0 (CVE-2026-12151), fetched
# during resolution then replaced at install time by the `^7.28.0` override in
# package.json. node_modules ships the fixed 7.28.0, but Trivy scans the stale
# cache tarball and fails the HIGH/CRITICAL image gate on a vuln that isn't
# actually installed. Dropping the cache clears the false positive (and shrinks
# the image); the build below only needs node_modules, never the cache.
RUN npm ci && npm cache clean --force

COPY . .

RUN npm run build

RUN chown -R node:node /app

USER node

EXPOSE 3333

CMD ["npm", "run", "dev", "--", "--host"]
