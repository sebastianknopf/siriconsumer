# Communication Profiles and Versions

Subscriptions select protocol behavior with the independent generic fields `profile` and `version`. If omitted, both default to `default`, which selects the standard SIRI common-denominator implementation.

The profile registry is keyed by `(profile, version)`. This allows incompatible generations of one profile to coexist, for example a future `de-vdv` version `3.1` alongside `de-vdv` version `2`.

## Consumer Callback URLs

The default profile is available without an explicit profile path:

```text
POST /
```

Explicit profiles use:

```text
/profile/{profileId}/{version}/{profile-specific-part}
```

The profile-specific part may be empty. Its syntax and meaning are owned by the selected profile. This keeps protocol-specific URL conventions out of the generic consumer routing layer.

## Available Profiles

- [`default` / `default`](profiles/default.md) describes the standard SIRI common profile and its configuration.
- [`de-vdv` / `2`](profiles/de-vdv-2.md) describes the VDV 453/454 2.x profile, SIRI-to-VDV service mapping, callback paths, and supported profile parameters.

## Generic Subscription Fields

The public subscription API always uses SIRI terminology. `profile` selects the profile family, `version` selects its implementation, and `parameters` carries optional profile-specific values. Profiles validate and interpret those values themselves.

The generic lifecycle, SQLite persistence, durable spool, retry handling, sinks, and optional communication logging remain independent of the selected profile.
