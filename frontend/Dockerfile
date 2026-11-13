FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build
FROM nginx:alpine
# Rendered by the nginx entrypoint at startup, so the API upstream can differ
# per environment (compose service vs. a Container Apps hostname).
ENV BACKEND_ORIGIN=http://backend:8000
COPY --from=build /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 05-set-resolvers.envsh /docker-entrypoint.d/05-set-resolvers.envsh
RUN chmod +x /docker-entrypoint.d/05-set-resolvers.envsh
EXPOSE 80
