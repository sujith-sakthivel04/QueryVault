import React from 'react';
import { expect, test } from 'vitest';
import { sellerLedgerColumns } from './SellerLedger';

const fields = (density: 'full' | 'compact' | 'narrow') =>
  sellerLedgerColumns(density, () => <span />).map((column) => column.field);

test('full seller ledger retains timestamp and complete quote columns', () => {
  expect(fields('full')).toEqual(['id', 'event', 'cents', 'quote_id', 'created_at']);
});

test('compact seller ledger drops the timestamp column while retaining quote IDs', () => {
  expect(fields('compact')).toEqual(['id', 'event', 'cents', 'quote_id']);
});

test('narrow seller ledger keeps its essential columns and moves full evidence to row details', () => {
  expect(fields('narrow')).toEqual(['id', 'event', 'cents']);
});
