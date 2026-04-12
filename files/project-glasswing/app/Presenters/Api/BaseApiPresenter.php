<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\TokenRepository;
use Nette\Application\UI\Presenter;
use Nette\Http\IResponse;

abstract class BaseApiPresenter extends Presenter
{
	/** @inject */
	public TokenRepository $tokenRepo;

	/** Override in subclasses to list actions that skip token auth */
	protected array $publicActions = [];

	public function startup(): void
	{
		parent::startup();
		$this->getHttpResponse()->setContentType('application/json', 'utf-8');

		// Skip token auth for explicitly public actions
		if (in_array($this->getAction(), $this->publicActions, true)) {
			return;
		}

		$this->requireTokenAuth();
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
