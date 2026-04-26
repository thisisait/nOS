# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Wing — security-research dashboard (Nette PHP-FPM).
#
# Hybrid pattern: nginx runs on the host (Homebrew on macOS, system pkg on
# Linux later) and forwards FastCGI to this container on 127.0.0.1:9000. The
# wing source tree lives on the host (rsync'd by pazny.wing) and is bind-
# mounted into the container at the SAME absolute path, so the SCRIPT_FILENAME
# values nginx sends (`/Users/.../wing/app/www/index.php`) resolve correctly
# inside FPM.
#
# This image therefore deliberately contains NO Wing source — only PHP-FPM,
# the runtime extensions Nette + the wing models need, and composer (so the
# `wing-cli` one-shot can run `composer install` against the bind-mount).
#
# Required mounts at runtime (compose handles this):
#   {{ wing_app_dir }}     → {{ wing_app_dir }}     rw   (same path on both sides)
# ─────────────────────────────────────────────────────────────────────────────
FROM php:8.3-fpm-alpine

ENV PHP_OPCACHE_ENABLE=1 \
    PHP_OPCACHE_VALIDATE_TIMESTAMPS=1 \
    COMPOSER_ALLOW_SUPERUSER=1 \
    COMPOSER_NO_INTERACTION=1 \
    COMPOSER_HOME=/tmp/composer

# Build deps + runtime libs:
#   build-base + autoconf + icu-dev: required to compile intl
#   sqlite-dev:                     pdo_sqlite + sqlite3 extensions
#   linux-headers:                  some PECL ext compiles need this
# We compile the native exts then drop the build-only packages to keep image
# size sane (~120 MB final vs ~250 MB without the cleanup).
RUN apk add --no-cache \
        icu-libs sqlite-libs \
        bash curl git unzip \
 && apk add --no-cache --virtual .build-deps \
        autoconf build-base icu-dev sqlite-dev linux-headers \
 && docker-php-ext-configure intl \
 && docker-php-ext-install -j"$(nproc)" \
        intl \
        pdo \
        pdo_sqlite \
        opcache \
 && pecl install apcu \
 && docker-php-ext-enable apcu \
 && apk del .build-deps \
 && rm -rf /tmp/pear ~/.pearrc

# Composer 2 — pin to a known-good version. Used for `composer install` via
# the wing-cli sidecar; the runtime FPM process never invokes it.
COPY --from=composer:2.7 /usr/bin/composer /usr/bin/composer

# Production-ish FPM tuning. Defaults are enough for a single-tenant home
# lab; deployments with more PHP load should override pm.* via php-fpm.d.
RUN { \
        echo "pm = dynamic"; \
        echo "pm.max_children = 8"; \
        echo "pm.start_servers = 2"; \
        echo "pm.min_spare_servers = 1"; \
        echo "pm.max_spare_servers = 4"; \
        echo "pm.max_requests = 500"; \
        echo "clear_env = no"; \
    } > /usr/local/etc/php-fpm.d/zz-wing.conf

# OPCache — full validation in dev (so source-edits show up live), fewer
# files cached because the Wing tree is small.
RUN { \
        echo "opcache.enable=1"; \
        echo "opcache.memory_consumption=64"; \
        echo "opcache.interned_strings_buffer=8"; \
        echo "opcache.max_accelerated_files=4000"; \
        echo "opcache.validate_timestamps=1"; \
        echo "opcache.revalidate_freq=2"; \
    } > /usr/local/etc/php/conf.d/zz-opcache.ini

# php.ini production profile + allow Nette's debug headers.
RUN cp /usr/local/etc/php/php.ini-production /usr/local/etc/php/php.ini \
 && sed -i 's/^expose_php = On/expose_php = Off/' /usr/local/etc/php/php.ini

# php-fpm runs as user `www-data` by default in the upstream image; that
# UID (82 in alpine) won't necessarily match the host user owning the
# bind-mounted source. We override the pool to run as a fixed UID we can
# chown the data dir to from the role.
ARG WING_UID=10082
ARG WING_GID=10082
RUN deluser www-data 2>/dev/null || true \
 && delgroup www-data 2>/dev/null || true \
 && addgroup -g "${WING_GID}" -S wing \
 && adduser  -u "${WING_UID}" -S -G wing -h /home/wing -s /bin/bash wing
RUN sed -i "s|^user = .*|user = wing|; s|^group = .*|group = wing|" \
        /usr/local/etc/php-fpm.d/www.conf

EXPOSE 9000

# Healthcheck: php-fpm exposes a status page if pm.status_path is set, but
# default-off avoids exposing internals. Use a TCP probe via nc (busybox).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD nc -z 127.0.0.1 9000 || exit 1

CMD ["php-fpm", "-F"]
