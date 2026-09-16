FROM node:26-alpine@sha256:725aeba2364a9b16beae49e180d83bd597dbd0b15c47f1f28875c290bfd255b9

# Upgrade npm to 11.x and patch npm's *bundled* undici.
#
# npm@11.17.0 (the newest release) vendors undici 6.26.0 — CVE-2026-12151, a
# HIGH DoS via unbounded memory. No npm release has shipped a fixed bundle yet,
# so we delete the vulnerable copy and install the patched undici 6.27.0 in the
# global root, where npm still resolves it (verified: npm and its registry/HTTP
# stack work against the relocated copy). The app's own undici is separately
# pinned to 7.28.0 via package.json overrides; this only concerns npm's vendored
# HTTP client. (npm 11 also drops the picomatch 4.0.3 ReDoS, CVE-2026-33671,
# that the older bundled npm on node:22-alpine carried.)
RUN npm install -g npm@11.17.0 && \
    rm -rf "$(npm root -g)/npm/node_modules/undici" && \
    npm install -g undici@6.27.0 && \
    npm cache clean --force

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
