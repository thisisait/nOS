<?php
/**
 * Plugin Name: nOS Devlog — enable Application Passwords behind the proxy
 * Description: WordPress core disables Application Passwords when the request
 * itself is not SSL. In nOS, TLS terminates at Traefik and every hop WP sees
 * is in-host (loopback publish 127.0.0.1:<port> or the docker bridge), so the
 * basic-auth credential never crosses an untrusted wire. The devlog sync
 * (files/anatomy/scripts/devlog-sync.py) and tools/devlog-post.py authenticate
 * with the nos-devlog-bot Application Password over exactly that path.
 * Staged by roles/pazny.wordpress (wordpress_devlog_enabled), mounted ro as a
 * mu-plugin — loads on every request, no activation step.
 */

add_filter('wp_is_application_passwords_available', '__return_true');
