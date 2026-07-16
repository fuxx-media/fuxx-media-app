FROM node:22-alpine AS dependencies

WORKDIR /app
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/mediaos-local-ca.pem
COPY .local-certs/ /tmp/mediaos-local-certs/
RUN touch "$NODE_EXTRA_CA_CERTS" \
    && if find /tmp/mediaos-local-certs -maxdepth 1 -type f -name '*.crt' | grep -q .; then \
      for certificate in /tmp/mediaos-local-certs/*.crt; do \
        cat "$certificate" >> /etc/ssl/certs/ca-certificates.crt; \
        cat "$certificate" >> "$NODE_EXTRA_CA_CERTS"; \
      done; \
    fi \
    && rm -rf /tmp/mediaos-local-certs
COPY package*.json ./
RUN npm install --global npm@11.6.2 \
    && npm ci --no-audit --no-fund

FROM node:22-alpine AS build

WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY --from=dependencies /app/node_modules ./node_modules
COPY package*.json ./
COPY frontend ./frontend
RUN npm run build:frontend

FROM node:22-alpine AS runtime

ENV NODE_ENV=production
WORKDIR /app
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/mediaos-local-ca.pem
COPY .local-certs/ /tmp/mediaos-local-certs/
RUN touch "$NODE_EXTRA_CA_CERTS" \
    && if find /tmp/mediaos-local-certs -maxdepth 1 -type f -name '*.crt' | grep -q .; then \
      for certificate in /tmp/mediaos-local-certs/*.crt; do \
        cat "$certificate" >> /etc/ssl/certs/ca-certificates.crt; \
        cat "$certificate" >> "$NODE_EXTRA_CA_CERTS"; \
      done; \
    fi \
    && rm -rf /tmp/mediaos-local-certs
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/frontend ./frontend
USER node
EXPOSE 3000
CMD ["npm", "run", "start:frontend"]
