import js from '@eslint/js';
import ts from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

/** Flat config. The XSS/no-`{@html}` doctrine is pinned by the repo's
 *  tests/anatomy gate (test_face_security_gates.py), not here — eslint enforces
 *  ordinary hygiene; the security gate is the hard, unbypassable boundary. */
export default ts.config(
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs['flat/recommended'],
	prettier,
	...svelte.configs['flat/prettier'],
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node }
		}
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parserOptions: { parser: ts.parser }
		}
	},
	{
		ignores: ['build/', '.svelte-kit/', 'node_modules/', 'package-lock.json']
	}
);
