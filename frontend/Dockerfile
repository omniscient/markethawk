FROM node:22-alpine@sha256:ab07539e0988b63558ff621f5fbe1077054c39d9809112974fb79993949d41cd

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
