# nOS PostGIS — the estate's own postgres image with PostGIS compiled in.
# Built per host (arm64 or amd64), so the PG minor is always the CVE pin
# `postgresql_version`; prebuilt multi-arch images lagged it (imresamu amd64 = 16.11).
# Same musl base as postgres:*-alpine, so an existing data dir keeps its collation.
# gdal-tools: the geo loaders run ogr2ogr here over the local socket (no new role).
ARG BASE=postgres:16.15-alpine
FROM ${BASE}

# No defaults: postgis_version + postgis_sha256 live in default.config.yml only.
ARG POSTGIS_VERSION
ARG POSTGIS_SHA256

RUN --mount=type=secret,id=nos_build_ca,required=false set -eux; \
    if [ -s /run/secrets/nos_build_ca ]; then export SSL_CERT_FILE=/run/secrets/nos_build_ca; fi; \
    apk add --no-cache --virtual .build-deps \
        build-base perl file gdal-dev geos-dev proj-dev json-c-dev libxml2-dev \
        pcre2-dev protobuf-c-dev wget; \
    wget -qO /tmp/postgis.tar.gz "https://download.osgeo.org/postgis/source/postgis-${POSTGIS_VERSION}.tar.gz"; \
    echo "${POSTGIS_SHA256}  /tmp/postgis.tar.gz" | sha256sum -c -; \
    mkdir /usr/src/postgis; tar -xzf /tmp/postgis.tar.gz -C /usr/src/postgis --strip-components 1; \
    cd /usr/src/postgis; \
    ./configure --without-gui --without-sfcgal; \
    make -j"$(nproc)" with_llvm=no; make install with_llvm=no; \
    apk add --no-cache --virtual .postgis-rundeps gdal gdal-tools gdal-driver-pg geos proj proj-data json-c libxml2 pcre2 protobuf-c libstdc++; \
    cd /; rm -rf /usr/src/postgis /tmp/postgis.tar.gz; apk del .build-deps
