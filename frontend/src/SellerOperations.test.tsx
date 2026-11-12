import React from 'react';
import { expect, test } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import SellerOperations from './SellerOperations';

const session = {
  id: 'fixture-session',
  state: 'settled',
  budget: 2000,
  spent: 105,
  reserved: 0,
  payment: {
    status: 'COMPLETED',
    amount: { currency_code: 'USD', value: '1.05' },
  },
};

const ledger = [
  { id: 704, event: 'quoted', quote_id: 'quote-070', cents: 70, created_at: '2026-11-09T10:00:00Z' },
  { id: 706, event: 'charged', quote_id: 'quote-070', cents: 70, created_at: '2026-11-09T10:01:00Z' },
  { id: 707, event: 'charged', quote_id: 'quote-035', cents: 35, created_at: '2026-11-09T10:02:00Z' },
];

const renderSeller = (active: typeof session) => renderToStaticMarkup(
  <SellerOperations evaluation={{}} catalogue={{}} ledger={ledger} active={active} />,
);

test('seller reconciliation uses recorded charges, a verified capture, and internal reservations as separate values', () => {
  const html = renderSeller(session);
  expect(html).toContain('Recorded query charges');
  expect(html).toContain('$1.05');
  expect(html).toContain('Independently verified collection');
  expect(html).toContain('Completed capture equals recorded query charges');
  expect(html).toContain('Internal reservations');
  expect(html).toContain('Held inside the query workflow; not a PayPal collection.');
  expect(html).toContain('$0.70');
  expect(html).toContain('$0.35');
  expect(html).toContain('No quote record');
});

test('seller reconciliation does not show an unverified provider amount as collected', () => {
  const unverified = {
    ...session,
    payment: { status: 'PENDING', amount: { currency_code: 'USD', value: '1.05' } },
  };
  const html = renderSeller(unverified);
  const collection = html.match(/class="reconciliation-node collection-node">([\s\S]*?)<\/div>/)?.[1] || '';
  expect(collection).toContain('Not verified');
  expect(collection).not.toContain('$1.05');
});
