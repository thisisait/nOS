<?php

declare(strict_types=1);

namespace App\Security;

/**
 * An end user the face BFF speaks for (files/anatomy/contracts/face-wing.yml, wire).
 *
 * Wing believes X-Nos-User-* only on a request whose bearer is the `face-bff`
 * row; every other token gets null and the headers are ignored. Pure, so the
 * gate runs it without Nette.
 */
final class EndUser
{
	public const TOKEN_NAME = 'face-bff';
	public const OPERATOR_GROUPS = ['nos-providers', 'nos-admins'];

	private function __construct(
		public readonly string $uid,
		public readonly bool $operator,
	) {
	}

	/**
	 * null = not a BFF request. Throws \DomainException (code 401) when the BFF
	 * bearer arrives without a canonical uid.
	 */
	public static function fromRequest(?string $tokenName, ?string $uid, ?string $groups): ?self
	{
		if ($tokenName !== self::TOKEN_NAME) {
			return null;
		}
		$uid = (string) $uid;
		if (!CanonicalUid::isCanonical($uid)) {
			throw new \DomainException('face-bff request without a canonical X-Nos-User-Uid', 401);
		}
		$set = preg_split('/[\s,|]+/', strtolower((string) $groups), -1, PREG_SPLIT_NO_EMPTY) ?: [];
		return new self($uid, (bool) array_intersect($set, self::OPERATOR_GROUPS));
	}

	public function actorId(): string
	{
		return 'user:' . $this->uid;
	}

	/** The actor a read is narrowed to; null = sees everything (Tier 1). */
	public function scope(): ?string
	{
		return $this->operator ? null : $this->actorId();
	}
}
