FROM node:20-slim AS build
WORKDIR /usr/src/app
ENV HUSKY=0

COPY package*.json ./
RUN npm ci

COPY tsconfig.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY index.html ./
COPY resources ./resources
COPY proprietary ./proprietary
COPY src ./src

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT="$GIT_COMMIT"
RUN npm run build-prod

FROM node:20-slim AS prod-deps
WORKDIR /usr/src/app
ENV HUSKY=0
ENV NPM_CONFIG_IGNORE_SCRIPTS=1
COPY package*.json ./
RUN npm ci --omit=dev

FROM node:20-slim
WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y nginx supervisor && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

COPY generate-nginx-upstream.sh /usr/local/bin/generate-nginx-upstream.sh
RUN chmod +x /usr/local/bin/generate-nginx-upstream.sh

COPY --from=prod-deps /usr/src/app/node_modules ./node_modules
COPY package*.json ./
COPY --from=build /usr/src/app/static ./static
COPY resources ./resources
RUN rm -rf ./resources/maps
COPY tsconfig.json ./
COPY src ./src

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > static/commit.txt
ENV GIT_COMMIT="$GIT_COMMIT"

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
