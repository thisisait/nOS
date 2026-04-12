<?php

/**
 * Router script for PHP built-in development server.
 * Usage: php -S 0.0.0.0:8099 -t www www/router.php
 */

$uri = urldecode(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH));

// Serve existing files directly (CSS, JS, images)
if ($uri !== '/' && file_exists(__DIR__ . $uri)) {
	return false;
}

// Route everything else through index.php (Nette front controller)
$_SERVER['SCRIPT_NAME'] = '/index.php';
require __DIR__ . '/index.php';
