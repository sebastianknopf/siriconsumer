# Communication Profiles and Versions

Subscriptions select protocol behavior with the independent generic fields `profile` and `version`. If omitted, both default to `default`, which selects the standard SIRI common-denominator implementation.

The profile registry is keyed by `(profile, version)`. This allows incompatible generations of one profile to coexist, for example `de-vdv` version `3.1` alongside `de-vdv` version `2`.

## Consumer Callback URLs

The default SIRI profile receives publisher callbacks at:

```text
POST /
```

VDV callbacks use the standard VDV endpoint shape without an explicit profile/version prefix:

```text
POST /{producer_ref}/{VDV-service}/{action}.xml
```

For VDV endpoints, the consumer maps the VDV service name to the public SIRI service code and looks up subscriptions by `(producer_ref, service)`. The persisted subscription rows determine the `profile` and `version` used to parse and answer the request. All `de-vdv` subscriptions sharing one `(producer_ref, service)` endpoint must therefore use the same profile version. Multiple subscriptions on that endpoint remain supported.

## Available Profiles

- [`default` / `default`](profiles/default.md) describes the standard SIRI common profile and its configuration.
- [`de-vdv` / `2`](profiles/de-vdv-2.md) describes the VDV 453/454 2.x profile, SIRI-to-VDV service mapping, callback paths, and supported profile parameters.
- [`de-vdv` / `3.1`](profiles/de-vdv-3.1.md) describes the VDV 453/454 3.1.0 profile, its service-specific subscription structures, and the backward-compatible extended filter model.

## Generic Subscription Fields

The public subscription API always uses SIRI terminology. `profile` selects the profile family, `version` selects its implementation, and `parameters` carries optional profile-specific values. Profiles validate and interpret those values themselves.

The generic lifecycle, SQLite persistence, durable spool, retry handling, sinks, and optional communication logging remain independent of the selected profile.

