<?php
/**
 * Plugin Name: nOS WordPress unauth-surface hardening (REM-114)
 * Description: Defense-in-depth for the intentionally-public CMS unauth surface.
 *              WordPress core is CVE-clean at the pinned 6.9.4, but the public
 *              endpoints below amplify brute-force / disclose usernames. This
 *              mu-plugin disables XML-RPC (system.multicall amplification +
 *              pingback SSRF), blocks anonymous REST user enumeration, and stops
 *              author-archive enumeration. Not a core patch — surface reduction.
 *              Part of the nOS Ansible playbook (roles/pazny.wordpress).
 */

if (!defined('ABSPATH')) {
    exit;
}

// 1. Disable XML-RPC entirely. `xmlrpc_enabled` only gates the AUTHENTICATED
//    (wp.*) methods — system.multicall (brute-force amplification) and demo.*
//    stay live under it. Emptying `xmlrpc_methods` removes EVERY method, so
//    xmlrpc.php answers "method does not exist" for all calls = inert. nOS uses
//    app-passwords + REST for legit remote access, not XML-RPC.
add_filter('xmlrpc_enabled', '__return_false');
add_filter('xmlrpc_methods', function () {
    return [];
});
add_filter('wp_headers', function ($headers) {
    unset($headers['X-Pingback']);
    return $headers;
});
remove_action('wp_head', 'rsd_link');

// 2. Block ANONYMOUS REST user enumeration (/wp-json/wp/v2/users*) — the
//    username-disclosure vector. Authenticated requests are untouched, so the
//    block editor's author picker still works for logged-in editors.
add_filter('rest_authentication_errors', function ($result) {
    if (!empty($result)) {
        return $result;
    }
    $route = $GLOBALS['wp']->query_vars['rest_route'] ?? '';
    if ($route === '' && isset($_SERVER['REQUEST_URI'])) {
        $route = (string) $_SERVER['REQUEST_URI'];
    }
    if (strpos($route, '/wp/v2/users') !== false && !is_user_logged_in()) {
        return new WP_Error(
            'rest_user_enumeration_blocked',
            'Authentication required.',
            ['status' => 401]
        );
    }
    return $result;
}, 20);

// 3. Stop author-archive enumeration (?author=N → 301 to /author/<login>/ leaks
//    the username). Redirect the numeric-author probe to home for anonymous hits.
add_action('template_redirect', function () {
    if (is_admin() || is_user_logged_in()) {
        return;
    }
    if (isset($_GET['author']) && is_numeric($_GET['author'])) {
        wp_safe_redirect(home_url('/'), 301);
        exit;
    }
});
