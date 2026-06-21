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
RUN npm ci

COPY . .

RUN npm run build

RUN chown -R node:node /app

USER node

EXPOSE 3333

CMD ["npm", "run", "dev", "--", "--host"]
