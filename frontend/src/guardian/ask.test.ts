import { describe, expect, it } from 'vitest'
import { ASK_COLUMNS, describeFilter, describeSort, toFilterModel, type AskFilter } from './ask'

describe('ask column description', () => {
  it('uses the grid column ids and lists every enum value', () => {
    const ids = ASK_COLUMNS.map((c) => c.id)
    expect(ids).toEqual(['payee', 'amount', 'level', 'category', 'evidence', 'status', 'decision', 'decidedBy',
      'checkedBy', 'created'])
    for (const c of ASK_COLUMNS) if (c.type === 'enum') expect(c.values?.length).toBeGreaterThan(1)
    expect(ASK_COLUMNS.find((c) => c.id === 'category')?.values).toContain('Bank impersonation')
  })
})

describe('filters to AG Grid', () => {
  it('builds text, number and date conditions', () => {
    const filters: AskFilter[] = [
      { column: 'level', operator: 'equals', value: 'high' },
      { column: 'amount', operator: 'greater_than', value: 200 },
      { column: 'payee', operator: 'contains', value: 'Collins' },
      { column: 'created', operator: 'after', value: '2026-11-03' },
    ]
    expect(toFilterModel(filters)).toEqual({
      level: { filterType: 'text', type: 'equals', filter: 'high' },
      amount: { filterType: 'number', type: 'greaterThan', filter: 200 },
      payee: { filterType: 'text', type: 'contains', filter: 'Collins' },
      created: { filterType: 'date', type: 'greaterThan', dateFrom: '2026-11-03 00:00:00', dateTo: null },
    })
  })

  it('handles ranges and combines two conditions on one column with AND', () => {
    expect(toFilterModel([{ column: 'amount', operator: 'between', value: 100, value_to: 1000 }])).toEqual({
      amount: { filterType: 'number', type: 'inRange', filter: 100, filterTo: 1000 },
    })
    expect(
      toFilterModel([
        { column: 'payee', operator: 'contains', value: 'a' },
        { column: 'payee', operator: 'contains', value: 'b' },
      ]),
    ).toEqual({
      payee: {
        filterType: 'text',
        operator: 'AND',
        conditions: [
          { filterType: 'text', type: 'contains', filter: 'a' },
          { filterType: 'text', type: 'contains', filter: 'b' },
        ],
      },
    })
  })
})

describe('chips in plain words', () => {
  it('describes filters and sorting', () => {
    expect(describeFilter({ column: 'level', operator: 'equals', value: 'high' })).toBe('Risk is High')
    expect(describeFilter({ column: 'amount', operator: 'greater_than', value: 200 })).toBe('Amount over $200')
    expect(describeFilter({ column: 'amount', operator: 'between', value: 100, value_to: 1000 })).toBe(
      'Amount $100 to $1,000',
    )
    expect(describeFilter({ column: 'decision', operator: 'equals', value: 'Declined' })).toBe('Decision is Declined')
    expect(describeFilter({ column: 'payee', operator: 'contains', value: 'Collins' })).toBe('Payee contains “Collins”')
    expect(describeFilter({ column: 'created', operator: 'after', value: '2026-11-03' })).toMatch(/^Date after Nov 3$/)
    expect(describeSort({ column: 'amount', direction: 'desc' })).toBe('Sorted by Amount, largest first')
  })
})
