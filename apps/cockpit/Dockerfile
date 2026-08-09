FROM node:22-alpine
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
WORKDIR /app
COPY . .
RUN pnpm install --no-frozen-lockfile && pnpm build
CMD ["pnpm", "preview"]
