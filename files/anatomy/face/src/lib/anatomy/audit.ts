/** How the Anatomy Wing view says the audit chain's verdict (row wing-inc2-agents-timeline).
 *  Off is said as off, a missing verdict as not yet, never as ok; only a known true is ok. */
import type { Tone } from '$lib/components/ui/tone';
import type { AuditVerdict } from '$lib/api/agents';

export function auditLine(v: AuditVerdict): { tone: Tone; badge: string; detail: string } {
	if (v.chain === 'off')
		return { tone: 'neutral', badge: 'audit chain off', detail: v.note ?? 'no signing key set' };
	if (v.chain !== 'on' || v.known !== true)
		return {
			tone: 'warn',
			badge: 'audit chain: no verdict',
			detail: v.note ?? 'the verify job has not reported'
		};
	return v.ok === true
		? {
				tone: 'ok',
				badge: 'audit chain intact',
				detail: v.verifiedAt ? `verified ${v.verifiedAt}` : ''
			}
		: {
				tone: 'bad',
				badge: 'audit chain BROKEN',
				detail: v.verifiedAt ? `as of ${v.verifiedAt}` : ''
			};
}
