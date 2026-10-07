<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\TokenRepository;
use App\Security\EndUser;
use Nette\Application\UI\Presenter;
use Nette\Http\IResponse;

abstract class BaseApiPresenter extends Presenter
{
	/** @inject */
	public TokenRepository $tokenRepo;

	/** Override in subclasses to list actions that skip token auth */
	protected array $publicActions = [];

	/** Non-empty: a $publicActions action skips token auth only on these methods. */
	protected array $publicMethods = [];

	/**
	 * Validated token row from requireTokenAuth(). NULL if the action
	 * is in $publicActions (HMAC-only path) or before startup() ran.
	 * Field of interest: $validatedToken['name'] — the operator/agent
	 * label (e.g. 'conductor', 'openclaw', 'ansible-provisioned'),
	 * surfaced as actor_id on writes via getActorId() (X.1.b).
	 *
	 * @var array<string,mixed>|null
	 */
	protected ?array $validatedToken = null;

	/** Actions the face-bff bearer may reach; each must narrow reads by endUser->scope(). */
	protected array $bffActions = [];

	/** The end user the face BFF speaks for, or null (face-wing.yml, wire). */
	protected ?EndUser $endUser = null;

	/** Estate-wide GETs the face-bff bearer reaches for a Tier-1 person only: nothing to narrow to. */
	protected array $bffOperatorReads = [];

	/** Actions that write an operator decision; startup() runs requireOperator() on each. */
	protected array $operatorActions = [];

	public function startup(): void
	{
		parent::startup();
		$this->getHttpResponse()->setContentType('application/json', 'utf-8');

		// Skip token auth for explicitly public actions
		if (in_array($this->getAction(), $this->publicActions, true)
			&& (!$this->publicMethods || in_array($this->getMethod(), $this->publicMethods, true))) {
			return;
		}

		$this->requireTokenAuth();

		if (!TokenRepository::permits($this->validatedToken['scopes'] ?? null, $this->getMethod())) {
			$this->sendError(
				'Token scope does not permit ' . $this->getMethod() . ' on the ops plane',
				IResponse::S403_Forbidden,
			);
		}

		$req = $this->getHttpRequest();
		try {
			$this->endUser = EndUser::fromRequest(
				$this->validatedToken['name'] ?? null,
				$req->getHeader('X-Nos-User-Uid'),
				$req->getHeader('X-Nos-User-Groups'),
			);
		} catch (\DomainException $e) {
			$this->sendError($e->getMessage(), IResponse::S401_Unauthorized);
		}
		// PHP method names are case-insensitive, so the match must be too.
		$operatorAction = in_array(strtolower($this->getAction()), array_map('strtolower', $this->operatorActions), true);
		$operatorRead = in_array($this->getAction(), $this->bffOperatorReads, true)
			&& in_array($this->getMethod(), ['GET', 'HEAD'], true);
		if ($this->endUser !== null && !$operatorAction && !$operatorRead && !in_array($this->getAction(), $this->bffActions, true)) {
			$this->sendError('the face-bff token does not reach this action', IResponse::S403_Forbidden);
		}
		if ($this->endUser !== null && $operatorRead && !$this->endUser->operator) {
			$this->sendError('This estate-wide read is Tier 1 (nos-providers or nos-admins) only', IResponse::S403_Forbidden);
		}
		if ($operatorAction) {
			$this->requireOperator();
		}
	}

	/**
	 * An operator decision needs the wing.operator scope, which no agent token holds
	 * (explicit-only: NULL grants nothing). Through the face BFF the person must also
	 * be Tier 1; a pure token holding the scope has no person to ask.
	 */
	protected function requireOperator(): void
	{
		if (!TokenRepository::grants($this->validatedToken['scopes'] ?? null, 'wing.operator')) {
			$this->sendError(
				'This is an operator decision: it needs the wing.operator scope, which agent tokens do not hold',
				IResponse::S403_Forbidden,
			);
		}
		if ($this->endUser !== null && !$this->endUser->operator) {
			$this->sendError(
				'This is an operator decision: Tier 1 (nos-providers or nos-admins) only',
				IResponse::S403_Forbidden,
			);
		}
	}

	private function requireTokenAuth(): void
	{
		$authHeader = $this->getHttpRequest()->getHeader('Authorization');
		if (!$authHeader || !str_starts_with($authHeader, 'Bearer ')) {
			$this->sendError('Missing or invalid Authorization header. Use: Authorization: Bearer <token>', 401);
		}

		$token = substr($authHeader, 7);
		$tokenData = $this->tokenRepo->validate($token);
		if (!$tokenData) {
			$this->sendError('Invalid or inactive API token', 401);
		}

		$this->validatedToken = $tokenData;
	}

	/**
	 * Resolve actor_id for A10 audit attribution (X.1.b, 2026-05-08).
	 *
	 * For Bearer-token writes the token row's `name` is the actor
	 * identifier (e.g. 'conductor', 'openclaw'); writes default to
	 * this when the payload doesn't override. For HMAC-only paths
	 * (Bone forwarding agent events) callers provide actor_id in the
	 * payload and this method returns null — the caller's value wins.
	 */
	protected function getActorId(): ?string
	{
		if ($this->endUser !== null) {
			return $this->endUser->actorId();
		}
		$name = $this->validatedToken['name'] ?? null;
		return is_string($name) && $name !== '' ? $name : null;
	}

	/** The actor a record names; refuses rather than write a default name. */
	protected function requireActorId(): string
	{
		$actor = $this->getActorId();
		if ($actor === null) {
			$this->sendError('No identity on this request, so nothing was recorded', IResponse::S401_Unauthorized);
		}
		return $actor;
	}

	protected function getJsonBody(): array
	{
		$raw = $this->getHttpRequest()->getRawBody();
		if (!$raw) {
			return [];
		}
		$data = json_decode($raw, true);
		if (!is_array($data)) {
			$this->sendError('Invalid JSON body');
		}
		return $data;
	}

	protected function sendSuccess(array $data, int $code = IResponse::S200_OK): never
	{
		$this->getHttpResponse()->setCode($code);
		$this->sendJson($data);
	}

	protected function sendError(string $message, int $code = IResponse::S400_BadRequest): never
	{
		$this->getHttpResponse()->setCode($code);
		$this->sendJson(['error' => $message, 'code' => $code]);
	}

	protected function sendCreated(array $data): never
	{
		$this->sendSuccess($data, IResponse::S201_Created);
	}

	protected function getMethod(): string
	{
		return $this->getHttpRequest()->getMethod();
	}

	protected function requireMethod(string ...$methods): void
	{
		if (!in_array($this->getMethod(), $methods, true)) {
			$this->sendError('Method not allowed', 405);
		}
	}
}
