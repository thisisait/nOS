import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('$lib/api/userstate', () => ({
	usGet: vi.fn(),
	usSet: vi.fn(() => Promise.resolve())
}));

import { usGet, usSet } from '$lib/api/userstate';
import {
	viewportBucket,
	toGeometry,
	createWindowCache,
	WINDOWS_NS,
	DEBOUNCE_MS
} from './window-cache';
import type { WindowModel, WindowGeometry } from '$lib/contracts';

const mockGet = vi.mocked(usGet);
const mockSet = vi.mocked(usSet);

function win(over: Partial<WindowModel> = {}): WindowModel {
	return {
		id: 'files-1',
		app: 'files',
		title: 'Files',
		x: 10,
		y: 20,
		w: 640,
		h: 440,
		z: 11,
		min: false,
		max: false,
		...over
	};
}

beforeEach(() => {
	mockGet.mockReset();
	mockSet.mockReset();
	mockSet.mockResolvedValue(undefined);
});

describe('viewportBucket', () => {
	it('rounds to the nearest 100 px', () => {
		expect(viewportBucket(1440, 900)).toBe('1400x900');
		expect(viewportBucket(1449, 851)).toBe('1400x900');
		expect(viewportBucket(1450, 900)).toBe('1500x900');
	});
	it('never buckets below 100', () => {
		expect(viewportBucket(10, 5)).toBe('100x100');
	});
});

describe('toGeometry', () => {
	it('keeps the persisted subset and drops title/max', () => {
		const g = toGeometry([win({ snappedCell: 'l' })]);
		expect(g).toEqual([
			{
				id: 'files-1',
				app: 'files',
				x: 10,
				y: 20,
				w: 640,
				h: 440,
				z: 11,
				min: false,
				snappedCell: 'l'
			}
		] satisfies WindowGeometry[]);
		expect(g[0]).not.toHaveProperty('title');
		expect(g[0]).not.toHaveProperty('max');
	});
	it('omits snappedCell when unset', () => {
		expect(toGeometry([win()])[0]).not.toHaveProperty('snappedCell');
	});
});

describe('createWindowCache — debounce', () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => vi.useRealTimers());

	it('coalesces writes and flushes once after the debounce window', () => {
		const adapter = createWindowCache({
			getViewport: () => ({ w: 1440, h: 900 }),
			debounceMs: DEBOUNCE_MS
		});

		adapter.onChange([win({ x: 1 })]);
		adapter.onChange([win({ x: 2 })]);
		adapter.onChange([win({ x: 3 })]);
		expect(mockSet).not.toHaveBeenCalled();

		vi.advanceTimersByTime(DEBOUNCE_MS);
		expect(mockSet).toHaveBeenCalledTimes(1);
		const [ns, key, value] = mockSet.mock.calls[0];
		expect(ns).toBe(WINDOWS_NS);
		expect(key).toBe('1400x900');
		expect((value as WindowGeometry[])[0].x).toBe(3); // latest coalesced
	});

	it('does not flush before the debounce elapses', () => {
		const adapter = createWindowCache({
			getViewport: () => ({ w: 800, h: 600 }),
			debounceMs: 30_000
		});
		adapter.onChange([win()]);
		vi.advanceTimersByTime(29_999);
		expect(mockSet).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(mockSet).toHaveBeenCalledTimes(1);
	});

	it('re-arms the timer for the next batch after a flush', () => {
		const adapter = createWindowCache({
			getViewport: () => ({ w: 800, h: 600 }),
			debounceMs: 1000
		});
		adapter.onChange([win({ x: 1 })]);
		vi.advanceTimersByTime(1000);
		adapter.onChange([win({ x: 9 })]);
		vi.advanceTimersByTime(1000);
		expect(mockSet).toHaveBeenCalledTimes(2);
		expect((mockSet.mock.calls[1][2] as WindowGeometry[])[0].x).toBe(9);
	});
});

describe('createWindowCache — restore', () => {
	it('reads the bucket for the current viewport', async () => {
		const saved: WindowGeometry[] = [
			{ id: 'files-1', app: 'files', x: 5, y: 5, w: 300, h: 200, z: 3, min: false }
		];
		mockGet.mockResolvedValue(saved);
		const adapter = createWindowCache({ getViewport: () => ({ w: 2560, h: 1440 }) });
		const out = await adapter.restore();
		expect(mockGet).toHaveBeenCalledWith(WINDOWS_NS, '2600x1400');
		expect(out).toEqual(saved);
	});

	it('returns null for an unseen viewport', async () => {
		mockGet.mockResolvedValue(null);
		const adapter = createWindowCache({ getViewport: () => ({ w: 1024, h: 768 }) });
		expect(await adapter.restore()).toBeNull();
	});

	it('swallows a restore error as null', async () => {
		mockGet.mockRejectedValue(new Error('boom'));
		const adapter = createWindowCache({ getViewport: () => ({ w: 1024, h: 768 }) });
		expect(await adapter.restore()).toBeNull();
	});
});
