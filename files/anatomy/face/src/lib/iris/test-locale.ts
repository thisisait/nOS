// Tests read in en whatever the host's LANG is: fmt.ts takes the shell locale from navigator.language.
// A vitest setupFile (vite.config.ts); nothing ships it.
Object.defineProperty(globalThis, 'navigator', { value: { language: 'en' }, configurable: true });
