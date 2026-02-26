# --- build stage ---
# Allow overriding base images via build-args (for users behind firewalls)
ARG BASE_NODE_IMAGE=node:18-alpine
ARG BASE_NGINX_IMAGE=nginx:1.25-alpine
FROM ${BASE_NODE_IMAGE} AS build
WORKDIR /app
COPY package.json ./
# Cache npm download/artifacts across builds
RUN --mount=type=cache,target=/root/.npm npm i --no-audit --no-fund
COPY . .
RUN npm run build

# --- runtime stage ---
FROM ${BASE_NGINX_IMAGE} AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx","-g","daemon off;"]
