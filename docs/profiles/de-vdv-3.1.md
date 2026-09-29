# German VDV Profile, Version 3.1

Use `profile: "de-vdv"` and `version: "3.1"` for VDV 453/454 version 3.1.0. The implementation targets the common schema revision `VDV453_incl_454_V3.1.0_v12` published by VDV for VDV 453 3.1.0 and VDV 454 3.1.0.

The profile uses fetched delivery and supports every VDV 453/454 subscription service represented by the consumer except AND: `CT`/REF-ANS, `CM`/ANS, `ST`/REF-DFI, `SM`/DFI, `VM`/VIS, `PT`/REF-AUS and `ET`/AUS. `producer_ref`, `initial_termination_time` and fetched delivery are required for every subscription.

## Common Routing

Inbound callbacks use:

`/profile/de-vdv/3.1/{ProducerRef}/{VDV-Service}/{Action}.xml`

For example:

`/profile/de-vdv/3.1/PRODUCER-LEIPZIG/AUS/datenbereit.xml`

The service mapping is:

| SIRI service | VDV service | Subscription element |
| --- | --- | --- |
| `CT` | `REF-ANS` | `AboASBRef` |
| `CM` | `ANS` | `AboASB` |
| `ST` | `REF-DFI` | `AboAZBRef` |
| `SM` | `DFI` | `AboAZB` |
| `VM` | `VIS` | `AboVIS` |
| `PT` | `REF-AUS` | `AboAUSRef` |
| `ET` | `AUS` | `AboAUS` |

## Filter Model

The public API keeps the existing generic `filters` pattern. Existing `filters.lines` and `filters.operators` requests remain unchanged. VDV 3.1 extends that same object with additional generic lists:

```json
{
  "filters": {
    "lines": ["de:vbb:11000000|Bus|100:2"],
    "directions": ["A"],
    "operators": ["85:11"],
    "products": ["Bus"],
    "vehicle_modes": ["NFB"],
    "stops": [
      [
        {"stop_id": "de:11000:900023201", "platform_id": "de:11000:900023201:1:50"},
        {"stop_id": "de:11000:900023173"}
      ],
      [
        {"stop_id": "de:11000:900023152"}
      ]
    ]
  }
}
```

`lines` maps to `LinienFilter/LinienID`; `directions` maps to `RichtungsID`. When both contain multiple values, the profile creates the Cartesian product, so every requested line is combined with every requested direction. `directions` without `lines` is rejected because VDV `LinienFilter` requires a line. CT/REF-ANS, CM/ANS time filters and VM/VIS allow at most one line and one direction.

For REF-AUS and AUS, different filter types are combined as AND conditions while multiple filters of the same type are alternatives (OR). `stops` represents VDV `HaltFilter` groups: each inner array becomes one `HaltFilter`; stop IDs within one inner array are AND conditions, while separate inner arrays are OR alternatives. A stop identifier can contain `stop_id` (`HaltestellenID`), `area_id` (`BereichsID`), `platform_id` (`SteigID`) and/or `sector_id` (`SektorenID`).

## Service Parameters

### CT / REF-ANS

Required: `parameters.asbId`, `parameters.earliestArrivalTime`, `parameters.latestArrivalTime`.

Optional: one `filters.lines` entry and one `filters.directions` entry.

### CM / ANS

Required: `parameters.asbId`, `parameters.hysteresis` and exactly one filter mode:

- `parameters.timeFilter`: one object containing required `earliestArrivalTime` and `latestArrivalTime`, plus optional `previewTime`. Optional line and direction restrictions are supplied through `filters.lines` and `filters.directions`.
- `parameters.journeyFilters`: one or more objects containing `journeyRef`, `operatingDay`, `stopSequenceCounter`, `plannedArrivalTime` and `previewTime`.

The two modes cannot be combined in one subscription.

### ST / REF-DFI

Required: `parameters.azbId`, `parameters.earliestDepartureTime`, `parameters.latestDepartureTime`.

Optional `filters.lines` and `filters.directions` restrict the requested lines/directions.

### SM / DFI

Required: `parameters.azbId`, `parameters.previewTime`, `parameters.hysteresis`.

Optional: `parameters.maxJourneys`, `parameters.maxTextLength`, `parameters.onlyUpdates`, plus `filters.lines` and `filters.directions`.

### VM / VIS

Required: `parameters.visId`.

Optional: one `filters.lines` entry and one `filters.directions` entry.

### PT / REF-AUS

Required: `parameters.validFrom`, `parameters.validUntil` for `Zeitfenster`.

Optional: `parameters.includeGuaranteedConnections`, `parameters.includeAdditionalTimeWindows`, `parameters.includeFormation` and all generic VDV 3.1 filters.

### ET / AUS

Required: `parameters.hysteresis`, `parameters.previewTime`.

Optional: `parameters.includeGuaranteedConnections`, `parameters.includeRealTimes`, `parameters.includeFormation`, `parameters.onlyUpdates` and all generic VDV 3.1 filters.

## REF-AUS Example

```json
{
  "provider_url": "https://publisher.example/vdv",
  "profile": "de-vdv",
  "version": "3.1",
  "service": "PT",
  "delivery_mode": "fetched",
  "requestor_ref": "CONSUMER",
  "subscriber_ref": "CONSUMER",
  "producer_ref": "PRODUCER",
  "subscription_ref": "ref-aus-1",
  "initial_termination_time": "2026-09-30T04:00:00+02:00",
  "parameters": {
    "validFrom": "2026-09-29T03:00:00+02:00",
    "validUntil": "2026-09-30T03:00:00+02:00",
    "includeFormation": true
  },
  "filters": {
    "lines": ["de:vbb:11000000|Bus|100:2"],
    "directions": ["A"],
    "operators": ["85:11"],
    "products": ["Bus"]
  },
  "sink": {"type": "directory", "path": "/data/ref-aus"}
}
```

The generated `AboAnfrage` includes `XSDVersionID="VDV453_incl_454_V3.1.0_v12"`. Data fetches explicitly send `DatensatzAlle=false`, so normal polling retrieves updated data; the existing `WeitereDaten` loop continues fetching subsequent packages.
