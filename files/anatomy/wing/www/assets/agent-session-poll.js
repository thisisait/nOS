// Auto-refresh an in-progress agent session detail view every 3s until
// the session reaches a terminal status. Loaded only when the server-
// side template confirms the session is still active (see
// app/Templates/Agents/session.latte conditional include).
//
// Extracted from inline <script> during W3 cleanup (Anatomy 2026-05-17).
(function () {
	var INTERVAL_MS = 3000;
	setTimeout(function () { window.location.reload(); }, INTERVAL_MS);
})();
