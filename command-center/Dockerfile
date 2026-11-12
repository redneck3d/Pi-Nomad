# --- 1. pmtiles CLI (used to cut regional map extracts). Built natively for arm64. ---
FROM golang:1-alpine AS pmtiles
RUN go install github.com/protomaps/go-pmtiles@latest \
 && mv /go/bin/go-pmtiles /pmtiles

# --- 2. Map viewer libraries and offline fonts/icons ---
FROM node:22-alpine AS mapassets
RUN apk add --no-cache git
WORKDIR /w
RUN npm init -y >/dev/null \
 && npm install maplibre-gl@5 pmtiles@4 @protomaps/basemaps@5 \
 && mkdir -p /out/lib /out/assets \
 && cp node_modules/maplibre-gl/dist/maplibre-gl.js node_modules/maplibre-gl/dist/maplibre-gl.css /out/lib/ \
 && cp node_modules/pmtiles/dist/pmtiles.js /out/lib/ \
 && cp node_modules/@protomaps/basemaps/dist/basemaps.js /out/lib/
# Protomaps' glyph (font) and sprite (icon) files, so labels render with no internet
RUN git clone --depth 1 https://github.com/protomaps/basemaps-assets /tmp/ba \
 && cp -r /tmp/ba/fonts /out/assets/fonts \
 && cp -r /tmp/ba/sprites /out/assets/sprites

# --- 3. The app itself (python stdlib only) ---
FROM python:3.12-alpine
WORKDIR /app
COPY --from=pmtiles /pmtiles /usr/local/bin/pmtiles
COPY *.py ./
COPY static ./static
COPY --from=mapassets /out/lib ./static/maps/lib
COPY --from=mapassets /out/assets ./static/maps/assets
ENV PORT=80
EXPOSE 80
CMD ["python", "-u", "app.py"]
