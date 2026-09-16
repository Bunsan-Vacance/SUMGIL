# Station Mapping Check

## Conclusion

The supplied station files are enough to build a reliable mapping, but the mapping must be coordinate-based. Numeric-only matching between OD `ST-*` IDs and hourly stock station numbers is invalid.

## Source Coverage

- Master rows: 3,430
- Master rows with valid Seoul coordinates: 3,353
- 2024 station info rows: 2,766
- 2025 station info rows: 2,799
- 2024 hourly stock station numbers: 3,127
- 2025 hourly stock station numbers: 2,804
- OD station IDs in 2024/2025 Q3: 2,848
- OD station IDs present in master CSV: 2,847

## Coordinate Mapping

- 6-decimal coordinate mapping, 2024: 2,525
- 6-decimal coordinate mapping, 2025: 2,559
- 6-decimal OD-ID intersection across 2024 and 2025 station info: 2,491
- 5-decimal coordinate mapping, 2024: 2,333
- 5-decimal coordinate mapping, 2025: 2,361

## Usable Mapping With Hourly Stock

- 2024 coordinate mappings whose stock station number appears in hourly data: 2,511
- 2025 coordinate mappings whose stock station number appears in hourly data: 2,541
- OD-ID intersection usable in both 2024 and 2025 hourly stock: 2,477

## Numeric Matching Risk

- Numeric-only exact matches, 2024: 1,848
- Numeric-only exact matches, 2025: 1,828
- Large coordinate gaps among numeric matches, 2024: 1,841
- Large coordinate gaps among numeric matches, 2025: 1,821

## Recommendation

Use this mapping key:

```text
OD master CSV: od_station_id + lat/lon
Station info Excel: station_no + lat/lon
Join: exact 6-decimal coordinate match first, then reviewed 5-decimal fallback if needed
```

Do not use:

```text
ST-987 -> 00987
```

The old Q3 dataset should be regenerated after applying this mapping.
