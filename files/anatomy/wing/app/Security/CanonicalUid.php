<?php

declare(strict_types=1);

namespace App\Security;

/**
 * THE canonical per-user partition key, PHP half.
 *
 * files/anatomy/face/src/lib/security/uid.ts::slugifyUid declares itself "THE
 * CANONICAL CONTRACT" — the face/Bone file tree (tenants/<slug>/users/<uid>/)
 * and KEAP's per-user-row owner are keyed on it. Until 2026-09-21 the Wing
 * invite flow was a SECOND writer of "the username": it accepted the raw
 * lowercased email local-part ([a-z0-9._-]), so `jan.novak@…` provisioned
 * Infisical `/users/<t>/jan.novak` and a `jan.novak@` mailbox while face/Bone
 * filed the same person under `jan-novak`. One person, two identities — this
 * class is the fold every PHP-side writer routes through.
 *
 * Byte-for-byte mirror of slugifyUid steps 2–4 (lowercase; every run of
 * non-[a-z0-9] → one dash; trim dashes; cap 64; re-trim). Step 1 (NFKD +
 * strip combining diacritics) runs only when ext-intl's Normalizer exists —
 * every current caller pre-validates its input to ASCII, so the intl-less
 * path is exercised with already-foldable bytes, never silently wrong ones.
 */
final class CanonicalUid
{
	public static function fold(string $s): string
	{
		if (class_exists(\Normalizer::class)) {
			$n = \Normalizer::normalize($s, \Normalizer::FORM_KD);
			if ($n !== false) {
				$s = preg_replace('/[\x{0300}-\x{036F}]/u', '', $n) ?? $s;
			}
		}
		$s = strtolower($s);
		$s = preg_replace('/[^a-z0-9]+/', '-', $s) ?? '';
		$s = trim($s, '-');
		$s = substr($s, 0, 64);
		return rtrim($s, '-');
	}
}
