/** The face Inbox app's client (row wing-inc1-inbox-app): /bff/inbox, Tier 1. */
import { bffGet, bffPost } from './client';
import type { AnswerOutcome, InboxNotification, InboxQuestion } from '$lib/inbox/project';

export type Inbox = {
	questions: InboxQuestion[];
	notifications: InboxNotification[];
	unread: number | null;
};

export function loadInbox(): Promise<Inbox> {
	return bffGet<Inbox>('/bff/inbox');
}

export async function markRead(uuid: string): Promise<void> {
	await bffPost('/bff/inbox', { op: 'read', uuid });
}

export function answerQuestion(
	uuid: string,
	answer: string
): Promise<{ uuid: string } & AnswerOutcome> {
	return bffPost<{ uuid: string } & AnswerOutcome>('/bff/inbox', { op: 'answer', uuid, answer });
}
