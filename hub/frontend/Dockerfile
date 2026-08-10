# Stage 0, "build-stage", based on Node.js, to build and compile the frontend
FROM node:20.19.5 AS build-stage

WORKDIR /app

COPY package*.json /app/

RUN npm install

COPY ./ /app/

# Our patched busytex engine (busytex.{js,wasm}) is committed and copied above.
# The large stock TeX Live *.data bundles are git-ignored; fetch them here so
# Vite bundles them into dist/. Skips files already present, so local builds
# (which have them on disk) are a no-op; fresh checkouts (CI/production) download
# them from the upstream busytex release.
RUN bash /app/scripts/download-tex-engine.sh

ARG VITE_API_URL
ARG VITE_STRIPE_PUBLISHABLE_KEY
ARG VITE_MIXPANEL_TOKEN
ARG VITE_GH_CLIENT_ID
ARG VITE_ZENODO_CLIENT_ID
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_TEXMF_PROXY

# Vite reads VITE_* at build time; promote build args to env vars for npm build
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_STRIPE_PUBLISHABLE_KEY=${VITE_STRIPE_PUBLISHABLE_KEY}
ENV VITE_MIXPANEL_TOKEN=${VITE_MIXPANEL_TOKEN}
ENV VITE_GH_CLIENT_ID=${VITE_GH_CLIENT_ID}
ENV VITE_ZENODO_CLIENT_ID=${VITE_ZENODO_CLIENT_ID}
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}
ENV VITE_TEXMF_PROXY=${VITE_TEXMF_PROXY}

RUN npm run build


# Stage 1, based on Nginx, to have only the compiled app, ready for production with Nginx
FROM nginx:1

COPY --from=build-stage /app/dist/ /usr/share/nginx/html

COPY ./nginx.conf /etc/nginx/conf.d/default.conf
COPY ./nginx-backend-not-found.conf /etc/nginx/extra-conf.d/backend-not-found.conf
