FROM node:24.15.0-bookworm AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:12026
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_ASSISTANT_ID=agent NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24.15.0-bookworm
WORKDIR /app
RUN corepack enable
COPY --from=build /app ./
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["pnpm", "start", "--hostname", "0.0.0.0", "--port", "3000"]
