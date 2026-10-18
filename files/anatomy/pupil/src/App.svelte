<!--
  The pupil: Iris (face/src/lib/iris) in a desktop window. The webview holds no socket and no
  secret; the Rust bridge owns ~/.nos/thalamus.sock and emits `to_shell` (decoded) and `link`
  events, and loads and saves the layout (workspace.rs). transport.tauri.ts is that bridge.
-->
<script lang="ts">
	import Iris from '$iris/Iris.svelte';
	import { tauriTransport } from './transport.tauri';

	const transport = tauriTransport();
</script>

<Iris {transport} />
