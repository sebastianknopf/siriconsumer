# Default SIRI Profile

Profile ID: `default`  
Version: `default`

This profile implements the standard SIRI common-denominator behavior used by the project before profile support was introduced. Omitting `profile` and `version` selects this profile automatically.

## Consumer URL

Publisher callbacks are received at:

```text
POST /consumer
```

The explicit equivalent is:

```text
POST /consumer/profile/default/default
```

## Publisher URL

`provider_url` is used directly for subscription, termination, status, and fetched-delivery requests. The profile does not append action-specific path components.

## Services

The profile supports the existing SIRI service codes `VM`, `SM`, `SX`, `ET`, `ST`, `PT`, and `FM`. Unknown service names continue to use the generic SIRI element naming behavior supported by the implementation.

## Profile Parameters

The default profile currently defines no keys in the generic `parameters` object. An omitted or empty object is therefore sufficient:

```json
"parameters": {}
```

Other generic subscription fields such as `requestor_ref`, `subscriber_ref`, `subscription_ref`, filters, heartbeat configuration, headers, delivery mode, and sink configuration retain their existing SIRI semantics.
