# --- build stage ---
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm i --no-audit --no-fund
COPY . .
RUN npm run build

# --- runtime stage ---
FROM nginx:1.25-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx","-g","daemon off;"]
