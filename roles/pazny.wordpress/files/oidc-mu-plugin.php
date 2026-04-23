<?php
/**
 * Plugin Name: nOS OIDC Bootstrap
 * Description: Auto-configures the `openid-connect-generic` plugin from env vars
 *              (WP_OIDC_*). Values are pushed via compose and kept in sync with
 *              the Authentik provider defined in `authentik_oidc_apps`.
 *              Drop-in (must-use) plugin — loaded automatically on every request,
 *              no UI activation needed. Part of the nOS Ansible playbook.
 * Author:      nOS
 * Version:     1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Sync OIDC settings into the wp_options table on every request. The
 * openid-connect-generic plugin reads `openid_connect_generic_settings`
 * (a single serialized array), so we merge env-provided values into that key.
 *
 * `update_option` is a no-op when the value is unchanged, so running this on
 * every init is cheap and state-declarative — the Ansible play is the source
 * of truth, the mu-plugin reconciles on the next page load.
 */
add_action('init', function () {
    $client_id     = getenv('WP_OIDC_CLIENT_ID') ?: '';
    $client_secret = getenv('WP_OIDC_CLIENT_SECRET') ?: '';
    $ep_login      = getenv('WP_OIDC_ENDPOINT_LOGIN') ?: '';
    $ep_userinfo   = getenv('WP_OIDC_ENDPOINT_USERINFO') ?: '';
    $ep_token      = getenv('WP_OIDC_ENDPOINT_TOKEN') ?: '';
    $ep_logout     = getenv('WP_OIDC_ENDPOINT_LOGOUT') ?: '';
    $scope         = getenv('WP_OIDC_SCOPE') ?: 'openid profile email';
    $login_type    = getenv('WP_OIDC_LOGIN_TYPE') ?: 'auto'; // auto | button
    $identity_key  = getenv('WP_OIDC_IDENTITY_KEY') ?: 'preferred_username';

    // Bail early if the core settings aren't wired. Keeps the plugin quiet on
    // hosts where Authentik is disabled.
    if ($client_id === '' || $ep_login === '' || $ep_token === '') {
        return;
    }

    $desired = [
        'login_type'                => $login_type,
        'client_id'                 => $client_id,
        'client_secret'             => $client_secret,
        'scope'                     => $scope,
        'endpoint_login'            => $ep_login,
        'endpoint_userinfo'         => $ep_userinfo,
        'endpoint_token'            => $ep_token,
        'endpoint_end_session'      => $ep_logout,
        'identity_key'              => $identity_key,
        'no_sslverify'              => 0,
        'http_request_timeout'      => 5,
        'enforce_privacy'           => 0,
        'alternate_redirect_uri'    => 0,
        'nickname_key'              => 'preferred_username',
        'email_format'              => '{email}',
        'displayname_format'        => '{given_name} {family_name}',
        'identify_with_username'    => 1,
        'state_time_limit'          => 180,
        'token_refresh_enable'      => 1,
        'link_existing_users'       => 1,
        'create_if_does_not_exist'  => 1,
        'redirect_user_back'        => 1,
        'redirect_on_logout'        => 1,
        'enable_logging'            => 0,
        'log_limit'                 => 1000,
    ];

    $current = get_option('openid_connect_generic_settings', []);
    if (!is_array($current)) {
        $current = [];
    }

    $merged = array_merge($current, $desired);

    if ($merged !== $current) {
        update_option('openid_connect_generic_settings', $merged);
    }
});
