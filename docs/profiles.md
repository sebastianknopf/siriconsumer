# Communication Profiles and Versions

Subscriptions select protocol behavior with two independent generic fields: `profile` and `version`. The separation is intentional so multiple incompatible versions of the same profile can coexist without encoding a version into the profile identifier.

If both fields are omitted, the subscription uses `profile: "default"` and `version: "default"`. This is the standard SIRI common-denominator implementation and preserves the previous behavior for existing subscription requests.

Registered combinations are currently:

| profile | version | specification | API services |
| --- | --- | --- | --- |
| `default` | `default` | Standard SIRI common profile | Standard SIRI service codes |
| `de-vdv` | `2` | VDV 453 2.6.1 / VDV 454 2.2.1, V2017e | `CT`, `CM`, `ST`, `SM`, `VM`, `PT`, `ET` |

A future implementation can therefore register `de-vdv` with version `3.1` independently of `de-vdv` version `2`.

## Consumer Callback URLs

The unversioned default endpoint is:

```text
POST /consumer
```

It always resolves to `default` the default profile.

All explicitly selected profiles use this base URL shape:

```text
/consumer/profile/{profileId}/{version}/{profile-specific-part}
```

The profile-specific part may be empty. For example, the explicit form of the default profile is:

```text
POST /consumer/profile/default/default
```

For `de-vdv` version `2`, the profile-specific path follows the VDV control-centre/service/action convention:

```text
/consumer/profile/de-vdv/2/{producer_ref}/{VDV-service}/{action}.xml
```

Examples:

```text
POST /consumer/profile/de-vdv/2/PRODUCER/AUS/datenbereit.xml
POST /consumer/profile/de-vdv/2/PRODUCER/AUS/clientstatus.xml
POST /consumer/profile/de-vdv/2/PRODUCER/VIS/datenbereit.xml
```

## Generic Subscription Fields

The public subscription API always uses SIRI terminology. Profiles map these values to their protocol-specific representation.

- `profile` selects the profile family. 
- `version` selects a concrete implementation of that profile. 
- `requestor_ref` is the consumer/requesting system identifier. For `de-vdv` version `2`, it becomes the VDV `Sender`. 
- `producer_ref` is the producer identifier agreed with the remote system and is required by `de-vdv` version `2` for inbound callback routing. 
- `subscription_ref` is the application-wide subscription identity and becomes the VDV `AboID`. 
- `parameters` carries profile-specific values without adding protocol-specific fields to the generic model.

## de-vdv Version 2

The public SIRI service codes map internally as follows:

| SIRI Service | VDV Service | VDV Subscription Element | Supported Parameters |
| --- | --- | --- | --- |
| `CT` | `REF-ANS` | `AboASBRef` | `asbId` |
| `CM` | `ANS` | `AboASB` | `asbId` |
| `ST` | `REF-DFI` | `AboAZBRef` | `azbId` |
| `SM` | `DFI` | `AboAZB` | `azbId` |
| `VM` | `VIS` | `AboVIS` | `visId` |
| `PT` | `REF-AUS` | `AboAUSRef` | none |
| `ET` | `AUS` | `AboAUS` | none |

`asbId`, `azbId`, and `visId` are required for the services that list them. They are read from the generic `parameters` object by the VDV profile only.

Example VIS subscription:

```json
{
  "provider_url": "https://publisher.example/vdv/vis",
  "profile": "de-vdv",
  "version": "2",
  "service": "VM",
  "delivery_mode": "fetched",
  "requestor_ref": "MY-CONSUMER",
  "subscriber_ref": "consumer",
  "producer_ref": "PRODUCER",
  "subscription_ref": "vis-17",
  "initial_termination_time": "2026-09-19T22:00:00Z",
  "parameters": {
    "visId": "VIS-AREA-12345"
  },
  "sink": {
    "type": "directory",
    "path": "/data/incoming/vis"
  }
}
```

For VDV, `provider_url` remains the configured publisher-side base URL. The profile resolves action-specific publisher endpoints such as `aboverwalten.xml`, `status.xml`, and `datenabrufen.xml`. No existing configuration field is renamed.

## Adding Profile Versions

A profile implementation declares a `profile_id` and a `version`. The registry keys implementations by the pair `(profile_id, version)`. Parsing, XML generation, endpoint resolution, service mapping, parameter validation, and fetched-delivery interpretation remain inside the selected profile. Core lifecycle, spool, retry, sink, and monitoring components remain profile-neutral.
