ARG BASE_NODE_IMAGE=docker.m.daocloud.io/library/node:20-alpine
ARG BASE_NGINX_IMAGE=docker.m.daocloud.io/library/nginx:1.25-alpine
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY

FROM ${BASE_NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm config delete proxy \
    && npm config delete https-proxy \
    && if [ -n "${HTTP_PROXY}" ]; then npm config set proxy "${HTTP_PROXY}"; fi \
    && if [ -n "${HTTPS_PROXY}" ]; then npm config set https-proxy "${HTTPS_PROXY}"; fi \
    && HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" ALL_PROXY="${ALL_PROXY}" npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM ${BASE_NGINX_IMAGE} AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
