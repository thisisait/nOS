<?php
/**
 * Plugin Name: nOS RBAC Role Sync
 * Description: Mirrors Authentik group membership into the WordPress role on
 *              every OIDC login. Reads WP_OIDC_GROUP_ROLE_MAP (JSON, rendered
 *              from `wordpress_rbac_role_map_json` by the wordpress-base
 *              compose extension) and assigns the HIGHEST-privilege mapped
 *              role found in the `groups` claim. Authentik is the identity
 *              source of truth: an OIDC user whose groups no longer map gets
 *              demoted to the fallback role. Local accounts (wp-admin
 *              break-glass, nos-devlog-bot) never traverse these hooks and
 *              are never touched. Part of the nOS Ansible playbook.
 * Author:      nOS
 * Version:     1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

/** Privilege order — higher index wins when multiple groups map. */
const NOS_RBAC_ROLE_ORDER = ['subscriber', 'contributor', 'author', 'editor', 'administrator'];
const NOS_RBAC_FALLBACK_ROLE = 'subscriber';

function nos_rbac_sync_role($user, $user_claim)
{
    if (!($user instanceof WP_User) || !is_array($user_claim)) {
        return;
    }
    $map_json = getenv('WP_OIDC_GROUP_ROLE_MAP') ?: '';
    if ($map_json === '') {
        return; // mirroring not configured — leave roles alone
    }
    $map = json_decode($map_json, true);
    if (!is_array($map) || $map === []) {
        return;
    }
    $groups = $user_claim['groups'] ?? [];
    if (!is_array($groups)) {
        $groups = [$groups];
    }

    $winner = NOS_RBAC_FALLBACK_ROLE;
    $winner_rank = -1;
    foreach ($groups as $group) {
        $role = $map[$group] ?? null;
        if ($role === null || !get_role($role)) {
            continue;
        }
        $rank = array_search($role, NOS_RBAC_ROLE_ORDER, true);
        $rank = ($rank === false) ? 0 : $rank;
        if ($rank > $winner_rank) {
            $winner = $role;
            $winner_rank = $rank;
        }
    }

    if (!in_array($winner, (array) $user->roles, true)) {
        $user->set_role($winner);
    }
}

// Fires on first OIDC login (user creation) and on every subsequent login
// when the plugin refreshes the user from the current claim.
add_action('openid-connect-generic-user-create', 'nos_rbac_sync_role', 10, 2);
add_action('openid-connect-generic-update-user-using-current-claim', 'nos_rbac_sync_role', 10, 2);
