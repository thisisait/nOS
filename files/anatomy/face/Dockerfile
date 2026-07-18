# =============================================================================
# nOS face — multi-stage build (vendored in-repo at files/anatomy/face/).
# roles/pazny.face points `docker compose build` at this context. The image
# bakes a HEALTHCHECK on /health so the STRICT in-stream health-wait sees a real
# health state (A19). SEC-02: the container joins ONLY the Traefik gated_net.
# =============================================================================
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
# adapter-node output + the pruned production deps.
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
ENV HOST=0.0.0.0 PORT=5090
EXPOSE 5090
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
	CMD node -e "fetch('http://127.0.0.1:'+ (process.env.PORT||5090) +'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "build/index.js"]
