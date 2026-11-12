import React, { useEffect, useMemo, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { money } from './api';
ModuleRegistry.registerModules([AllCommunityModule]);

type LedgerRow = Record<string, unknown>;
export type LedgerDensity = 'full' | 'compact' | 'narrow';

const shortQuoteId = (value: unknown) => String(value || '').slice(0, 8);
const readableEvent = (value: unknown) => String(value || 'Unknown event').replaceAll('_', ' ');

export function formatLedgerTimestamp(value: unknown) {
  const exact = String(value || '');
  const parsed = new Date(exact);
  if (Number.isNaN(parsed.valueOf())) return exact || 'Unknown time';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(parsed);
}

function timestampCell(params: ICellRendererParams<LedgerRow>) {
  const exact = String(params.value || '');
  const display = formatLedgerTimestamp(exact);
  return <time dateTime={exact || undefined} title={'Exact timestamp: ' + exact} aria-label={display + '; exact timestamp ' + exact}>{display}</time>;
}

export function sellerLedgerColumns(density: LedgerDensity, timestampRenderer = timestampCell): ColDef<LedgerRow>[] {
  const id: ColDef<LedgerRow> = { field: 'id', headerName: 'ID', width: 58, minWidth: 48, maxWidth: 70 };
  const event: ColDef<LedgerRow> = {
    field: 'event',
    flex: 1,
    minWidth: density === 'full' ? 145 : density === 'compact' ? 82 : 84,
    valueFormatter: params => readableEvent(params.value),
  };
  const amount: ColDef<LedgerRow> = {
    field: 'cents', headerName: 'Amount', width: density === 'full' ? 118 : density === 'compact' ? 70 : 74,
    minWidth: density === 'full' ? 118 : 68,
    cellClass: 'numeric-cell',
    headerClass: 'ag-right-aligned-header',
    valueFormatter: params => money(Number(params.value || 0)),
  };
  const quote: ColDef<LedgerRow> = {
    field: 'quote_id',
    headerName: 'Quote',
    width: 96,
    minWidth: 92,
    maxWidth: density === 'full' ? undefined : 112,
    valueFormatter: params => shortQuoteId(params.value),
    tooltipValueGetter: params => params.value ? 'Full quote ID: ' + String(params.value) : 'No quote linked',
  };
  const created: ColDef<LedgerRow> = {
    field: 'created_at',
    headerName: 'Created',
    flex: 1,
    minWidth: 165,
    cellRenderer: timestampRenderer,
    tooltipValueGetter: params => 'Exact timestamp: ' + String(params.value || ''),
    comparator: (a, b) => {
      const left = Date.parse(String(a || ''));
      const right = Date.parse(String(b || ''));
      return Number.isNaN(left) || Number.isNaN(right) ? 0 : left - right;
    },
  };

  if (density === 'narrow') return [id, event, amount];
  if (density === 'compact') return [id, event, amount, quote];
  return [id, event, amount, { ...quote, headerName: 'Quote ID', flex: 1, maxWidth: undefined }, created];
}

function viewportDensity(): LedgerDensity {
  if (typeof window === 'undefined') return 'full';
  if (window.matchMedia('(max-width: 360px)').matches) return 'narrow';
  if (window.matchMedia('(max-width: 600px)').matches) return 'compact';
  return 'full';
}

export default function SellerLedger({ ledger, filter, selectedId, onSelect }: {
  ledger: LedgerRow[];
  filter: string;
  selectedId?: unknown;
  onSelect: (row: LedgerRow) => void;
}) {
  const [density, setDensity] = useState<LedgerDensity>(viewportDensity);
  useEffect(() => {
    const compact = window.matchMedia('(max-width: 600px)');
    const narrow = window.matchMedia('(max-width: 360px)');
    const update = () => setDensity(narrow.matches ? 'narrow' : compact.matches ? 'compact' : 'full');
    update();
    compact.addEventListener('change', update);
    narrow.addEventListener('change', update);
    return () => {
      compact.removeEventListener('change', update);
      narrow.removeEventListener('change', update);
    };
  }, []);

  const columnDefs = useMemo(() => sellerLedgerColumns(density), [density]);
  const defaultColDef = useMemo(() => ({ sortable: true, filter: density === 'full', resizable: density === 'full' }), [density]);
  return (
    <div className="seller-grid" aria-label="Searchable transaction ledger">
      <AgGridReact
        rowData={ledger}
        quickFilterText={filter}
        rowSelection={{ mode: 'singleRow', checkboxes: false, enableClickSelection: true }}
        onRowClicked={event => { if (event.data) onSelect(event.data); }}
        rowClassRules={{ 'ledger-row-selected': params => params.data?.id === selectedId }}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
      />
    </div>
  );
}
