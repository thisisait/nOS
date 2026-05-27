<?php

declare(strict_types=1);

namespace App\Presenters;

use Nette;
use Nette\Application\Request;
use Nette\Application\Response;
use Nette\Application\Responses\CallbackResponse;
use Nette\Http\IRequest;
use Nette\Http\IResponse;
use Tracy\Debugger;
use Tracy\ILogger;

/**
 * Minimal error presenter. common.neon sets `errorPresenter: Error`, but the
 * class was missing — masked while debug mode was always-on (the
 * setDebugMode('127.0.0.1') bug: Wing binds loopback so Traefik proxied every
 * request from 127.0.0.1, keeping Tracy on for all traffic). Once debug was
 * gated behind WING_TRACY_SECRET, the absence surfaced: any production error
 * threw InvalidLinkException and fell back to Tracy's generic "Server Error"
 * page, which leaks `<meta generator=Tracy>` + the framework.
 *
 * This renders a clean, generator-free 4xx/5xx page and logs non-4xx. It
 * implements IPresenter directly (NOT BasePresenter) so the edge-trust guard
 * does not re-fire during error handling, and takes no DI deps so it can never
 * fail to construct while handling another failure.
 */
final class ErrorPresenter implements Nette\Application\IPresenter
{
	public function run(Request $request): Response
	{
		$exception = $request->getParameter('exception');
		$code = $exception instanceof Nette\Application\BadRequestException
			? ($exception->getHttpCode() ?: 404)
			: 500;

		// 4xx are client errors (expected); log everything else for the operator.
		if (!($exception instanceof Nette\Application\BadRequestException)) {
			Debugger::log($exception, ILogger::EXCEPTION);
		}

		return new CallbackResponse(function (IRequest $httpRequest, IResponse $httpResponse) use ($code): void {
			$httpResponse->setCode($code);
			$httpResponse->setContentType('text/html', 'UTF-8');
			$title = $code >= 500 ? 'Server Error' : 'Page Not Found';
			$detail = $code >= 500
				? 'An error occurred and has been logged. Please try again later.'
				: 'The page you requested could not be found.';
			echo '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
				. '<meta name="viewport" content="width=device-width, initial-scale=1">'
				. '<meta name="robots" content="noindex">'
				. '<title>' . $code . ' — ' . $title . '</title>'
				. '<style>body{font:16px/1.5 system-ui,-apple-system,sans-serif;color:#222;'
				. 'background:#fafafa;margin:0;display:flex;min-height:100vh;align-items:center;'
				. 'justify-content:center}main{max-width:30rem;padding:2rem;text-align:center}'
				. 'h1{font-size:3rem;margin:0 0 .5rem;color:#b079d6}p{color:#666;margin:0}</style>'
				. '</head><body><main><h1>' . $code . '</h1><p>'
				. htmlspecialchars($title, ENT_QUOTES) . '</p><p>'
				. htmlspecialchars($detail, ENT_QUOTES) . '</p></main></body></html>';
		});
	}
}
