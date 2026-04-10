# ProShop GraphQL API — Offline Reference

> Compiled from the official ProShop API Developer Documentation
> Source: https://adionsystems.atlassian.net/wiki/spaces/PADD/overview
> Last updated: April 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Authentication](#2-authentication)
   - 2.1 [Managing Authorizations (API Keys)](#21-managing-authorizations-api-keys)
   - 2.2 [Begin Session (Username/Password)](#22-begin-session-usernamepassword)
   - 2.3 [OAuth 2.0 Authorization Code Flow](#23-oauth-20-authorization-code-flow)
   - 2.4 [OAuth 2.0 Client Credentials Flow](#24-oauth-20-client-credentials-flow)
   - 2.5 [End Session (Logout)](#25-end-session-logout)
3. [Querying the GraphQL API](#3-querying-the-graphql-api)
4. [Common Data Structures](#4-common-data-structures)
   - 4.1 [Paginated Lists](#41-paginated-lists)
   - 4.2 [Filters](#42-filters)
5. [The Recently Updated Records API](#5-the-recently-updated-records-api)
6. [Setting Up Altair GraphQL Client](#6-setting-up-altair-graphql-client)
7. [ProShop API Playground (v5.2.3+)](#7-proshop-api-playground-v523)
8. [Authorization Scopes — Quick Reference](#8-authorization-scopes--quick-reference)

---

## 1. Introduction

ProShop provides a **GraphQL API** available via HTTPS. All calls are HTTP POST requests to a single endpoint:

```
POST https://YOUR-PROSHOP-SERVER/api/graphql
Content-Type: application/json
```

The JSON body has three components:

| Field           | Type   | Description |
|-----------------|--------|-------------|
| `query`         | String | The full GraphQL document to execute |
| `variables`     | Object | Values for any variables referenced in the query |
| `operationName` | String | Which operation to execute if the document has multiple |

### Query Patterns

The schema exposes two query patterns per module:

- **Singular** (e.g. `workOrder`) — accepts a unique ID argument (e.g. `workOrderNumber`) and returns one record.
- **Plural** (e.g. `workOrders`) — accepts `filter`, `pageSize`, and `pageStart` arguments and returns a paginated list.

The schema itself is introspectable via the standard GraphQL introspection query. Use a client like [Altair](https://altairgraphql.dev/) or the built-in ProShop Playground to explore it.

---

## 2. Authentication

Every API call requires a valid access token. ProShop supports three ways to obtain one.

### 2.1 Managing Authorizations (API Keys)

Before using the Client Credentials flow, a system administrator must create an Authorization in ProShop:

1. Log into ProShop as a system administrator
2. Open **System Config**
3. Click **Manage Authorizations** in the Configuration Links panel
4. Fill out **Name** and **Maximum Scope** in a new row
5. Check **Direct Login** to enable the Client Credentials flow
6. Check **Active**
7. Click **Save Changes**

The table will show a **Unique ID** (client_id) and a **Shared Secret** (client_secret) — click "Click here to view Client Secrets" to reveal them.

---

### 2.2 Begin Session (Username/Password)

The simplest authentication method. Authenticates a user and returns a session token.

**Endpoint:** `POST /api/beginsession`

**Request Body (JSON):**

```json
{
  "username": "janedoe@gmail.com",
  "password": "Your password here",
  "scope": "users:r workorders:rwdp invoices:rp"
}
```

**200 Success Response:**

```json
{
  "authorizationResult": {
    "fileAccessSecurityGroup": null,
    "sessionValidForSeconds": 300,
    "sessionValidFrom": "2022-05-30T210622Z",
    "token": "F2C9FD536B9D85B7D35F1846D5E7FF61490E96EDB64CCBFD71C2EC2F3B99382D",
    "userGroup": "",
    "userId": "000",
    "userName": "janedoe@gmail.com"
  },
  "warning": "//warning message here//"
}
```

**Response Fields (`authorizationResult`):**

| Field                    | Type    | Description |
|--------------------------|---------|-------------|
| `userName`               | String  | The authenticated user's email |
| `userId`                 | String  | User ID (typically an integer as string) |
| `userGroup`              | String  | User's group |
| `token`                  | String  | Session token for all subsequent API calls |
| `sessionValidFrom`       | String  | UTC creation date, format `yyyy-MM-ddThhmmssZ` |
| `sessionValidForSeconds` | Integer | Token lifespan in seconds |

**401 Unauthorized:**

```json
{
  "apiError": "Invalid Credentials"
}
```

---

### 2.3 OAuth 2.0 Authorization Code Flow

For interactive web applications that need to act on behalf of a specific user.

#### Step 1: Redirect

Redirect the user's browser to ProShop's authorization page.

**Endpoint:** `GET /home/member/oauth/authorization`

| Parameter      | Type   | Required | Description |
|---------------|--------|----------|-------------|
| `response_type` | string | Yes | Must be `"code"` |
| `client_id`    | string | Yes | Your application's unique ID from ProShop |
| `scope`        | string | Yes | URL-encoded, space-delimited module list |
| `redirect_uri` | url    | Yes | URL-encoded callback URI (must match authorization config) |
| `state`        | string | No  | Anti-CSRF token |

**Example:**

```
GET https://yourco.adionsystems.com/home/member/oauth/authorization?
  response_type=code
  &client_id=F2C9-FD53-6B9DF
  &redirect_uri=https%3A%2F%2Fmy.apps.domain%2Fredirect
  &state=F61490E96EDB64CCBFD71C2EC2F3B9
  &scope=users%20workorders
```

#### Step 2: User Approval

The user sees the authorization page and approves or denies.

**If approved**, redirect includes:

| Parameter | Description |
|-----------|-------------|
| `code`    | Authorization code (valid 5 minutes) |
| `state`   | Echoed back if provided |

```
GET https://my.apps.domain/redirect?
  code=8212F3F11A3910787D7B96BEE4
  &state=F61490E96EDB64CCBFD71C2EC2F3B9
```

**If denied**, redirect includes:

| Parameter           | Description |
|--------------------|-------------|
| `error`            | `"user_cancelled_authorize"` or `"user_cancelled_login"` |
| `error_description` | URL-encoded description |

#### Step 3: Exchange Code for Token

**Endpoint:** `POST /home/member/oauth/accessToken`

**Content-Type:** `application/x-www-form-urlencoded`

| Parameter       | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `grant_type`    | string | Yes | Must be `"authorization_code"` |
| `client_id`     | string | Yes | Your application's unique ID |
| `client_secret` | string | Yes | Your application's secret key |
| `redirect_uri`  | url    | Yes | Must match the one used in Step 1 |
| `code`          | string | Yes | The authorization code from Step 2 |
| `scope`         | string | Yes | Same scope or subset |

**Success Response:**

```json
{
  "access_token": "F2C9FD536B9D85B7D35F1846D5E7FF61490E96EDB64CCBFD71C2EC2F3B99382D",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

| Field          | Type    | Description |
|---------------|---------|-------------|
| `access_token` | String  | 64-char session token (may grow in future) |
| `expires_in`   | Integer | Seconds until expiration (default 24 hours) |

---

### 2.4 OAuth 2.0 Client Credentials Flow

For server-to-server applications with no user interaction. **This is the recommended flow for the Odoo integration.**

Available as of ProShop v5.2.3.

**Endpoint:** `POST /home/member/oauth/accesstoken`

**Content-Type:** `application/x-www-form-urlencoded`

| Field           | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `grant_type`    | string | Yes | Must be `"client_credentials"` |
| `client_id`     | string | Yes | Format `XXXX-XXXX-XXXX` (hex) |
| `client_secret` | string | Yes | Treat like a password |
| `scope`         | string | No  | If omitted, uses the authorization's maximum scope |

**Example:**

```
POST https://yourco.adionsystems.com/home/member/oauth/accesstoken
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
client_id=1234-5678-90AB&
client_secret=1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF&
scope=customerpo:rwd+users:r+contacts:rw
```

**Success:**

```json
{
  "access_token": "1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

**Error:**

```json
{
  "error": "invalid_client",
  "error_description": "A nonexistent or invalid client_id was passed."
}
```

---

### 2.5 End Session (Logout)

Terminates an active session.

**Endpoint:** `GET /api/endsession?token=<TOKEN>`

**200 Success:** Returns `endSessionResult` confirming the session was ended.

**422 Unprocessable Entity:** Token authentication failed. May include an `apiError` object.

---

## 3. Querying the GraphQL API

This is the main endpoint for all data queries and mutations.

**Endpoint:** `POST /api/graphql`

**Authorization** — provide the token via one of:

**Bearer Token (header):**

```http
POST https://yourco.adionsystems.com/api/graphql
Content-Type: application/json
Authorization: Bearer <TOKEN>

{
  "query": "{...graphql goes here}"
}
```

**Query String:**

```http
POST https://yourco.adionsystems.com/api/graphql?token=<TOKEN>
Content-Type: application/json

{
  "query": "{...graphql goes here}"
}
```

**Request Body:**

| Field           | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `query`         | String (GraphQL) | Yes | The full GraphQL document |
| `operationName` | String | No  | Names which operation to execute if multiple are defined |
| `variables`     | JSON Object | No | Variable values referenced in the query |

**Example Request:**

```json
{
  "query": "query contact ($name: String!) {\n  contact (name: $name) {\n    accountingGuid\n    accountingVendorGuid\n    accountNumber\n  }\n}",
  "variables": { "name": "Joe Shmoe" }
}
```

### Responses

**200 Success** — all GraphQL responses return 200, even errors:

| Field    | Type             | Description |
|---------|------------------|-------------|
| `data`   | Object           | Query result data (absent on total query failure) |
| `errors` | Array of Strings | Any execution errors (absent on success) |

**422 Unprocessable Entity:**

```json
{
  "apiError": "Invalid Credentials"
}
```

---

## 4. Common Data Structures

### 4.1 Paginated Lists

Most plural queries (e.g. `workOrders`, `contacts`) return paginated results.

**Arguments:**

| Argument    | Type    | Default | Description |
|------------|---------|---------|-------------|
| `pageSize`  | Integer | 20 | Records per page (no hard upper limit) |
| `pageStart` | Integer | 0  | Zero-based index of first record |
| `filter`    | Object  | — | Module-specific filter criteria |
| `query`     | Object  | — | More detailed search (where available) |

**Returned Fields:**

| Field          | Type    | Description |
|---------------|---------|-------------|
| `records`      | Array   | The data objects for the current page |
| `totalRecords` | Integer | Total matching records across all pages |
| `pageSize`     | Integer | Echo of the pageSize argument |
| `pageStart`    | Integer | Echo of the pageStart argument |

**Pagination loop pattern:**

```graphql
# Page 1
query { workOrders(pageSize: 50, pageStart: 0) { totalRecords records { workOrderNumber } } }

# Page 2
query { workOrders(pageSize: 50, pageStart: 50) { totalRecords records { workOrderNumber } } }

# Continue until pageStart >= totalRecords
```

---

### 4.2 Filters

Filters narrow query results similar to ProShop's Advanced Search. Filter field types:

#### Booleans

Single `true` or `false` value.

#### Strings

Array of values — matches any value in the array.

```graphql
filter: { status: ["Open", "Closed"] }
```

#### Enums

Array of named options from a predefined list (visible via introspection).

#### Numbers (Float / Int)

Object with comparison operators. All specified conditions must match.

| Field                | Description |
|---------------------|-------------|
| `exactly`            | Exact match |
| `greaterThan`        | Strictly greater than |
| `greaterThanOrEqual` | Greater than or equal to |
| `lessThan`           | Strictly less than |
| `lessThanOrEqual`    | Less than or equal to |

```graphql
filter: { quantity: { greaterThanOrEqual: 10, lessThan: 100 } }
```

#### Dates

Same five comparison operators as numbers, but values are ISO 8601 strings.

```graphql
filter: { lastModifiedTime: { greaterThan: "20260101T000000" } }
```

Reference: [W3C Date and Time Formats](https://www.w3.org/TR/NOTE-datetime)

---

## 5. The Recently Updated Records API

A high-performance REST endpoint for retrieving recently created, modified, or deleted records. More efficient than filtering by `lastModifiedTime` in GraphQL for polling workflows.

> Must be enabled by the ProShop team.

**Endpoint:** `GET /recentlyupdatedrecords`

**Authentication:** Same token-based auth as the GraphQL endpoint.

### Parameters

| Argument   | Type           | Required | Description |
|-----------|----------------|----------|-------------|
| `start`    | ISO 8601 date  | Yes | Only records changed after this time |
| `end`      | ISO 8601 date  | No  | Only records changed before this time (defaults to now) |
| `filterby` | String (CSV)   | No  | Comma-delimited record types to include |

### ISO 8601 Format

`YYYYMMDDTHHMMSS` with optional `Z` suffix for UTC.

Example: `20260305T140500Z` = March 5, 2026 at 2:05 PM UTC

### Example Request

```
GET https://yourco.adionsystems.com/recentlyupdatedrecords?
  start=20260305T140400Z
  &end=20260312T000000Z
  &filterby=workorders,customerpos,quotes
```

### Example Response

```json
{
  "start_utc": "20260305T000000",
  "end_utc": "20260312T000000",
  "filter_by": "workorders,customerpos,quotes",
  "records": {
    "workorders": {
      "20260311T164322/00002": {
        "group": "2018",
        "modDate": "2026-03-11T195723Z",
        "name": "18-0163",
        "type": "workOrder",
        "type_plural": "workOrders"
      }
    }
  }
}
```

### Recommended Polling Pattern for Odoo Integration

1. Poll `/recentlyupdatedrecords` every N minutes, filtered to the record types you care about
2. Get back a list of changed record names/IDs
3. Use direct GraphQL lookups for the changed records to get full details
4. Update CRM leads in Odoo accordingly

This two-step approach (poll for changes, then fetch details) is much faster than scanning all records.

### Available `filterby` Values

| Filter | Filter | Filter |
|--------|--------|--------|
| approvals | auditreports | bills |
| classifications | clockpunches | companypositions |
| contacts | correctiveactionrequests | **customerpos** |
| customersurveys | documents | editlog |
| equipments | **estimates** | estimatesarchive |
| fixtures | formats | invoices |
| messages | nonconformancereports | cotsitems |
| packingslips | parts | partsarchive |
| pars | purchaseorders | vendorpos |
| qualitymanual | qualityprocedures | **quotes** |
| returnmaterialauthorizations | rtas | standards |
| tasks | workcells | tools |
| trainings | users | **workorders** |
| timetracking | timeclock | deletions |

> Bold entries are the most relevant for the Miltech CRM integration.

---

## 6. Setting Up Altair GraphQL Client

[Altair](https://altairgraphql.dev/) is the recommended desktop client for exploring the API.

### Environment Setup

Create an environment with these variables:

```json
{
  "doAuth": true,
  "endpointUrl": "https://yourco.adionsystems.com",
  "username": "signup email",
  "password": "password",
  "scope": "space delimited list of modules"
}
```

### Post URL

Set method to `POST` and URL to:

```
{{endpointUrl}}/api/graphql?token={{token}}
```

### Pre-Request Script

Enable pre-requests and paste this script to auto-authenticate:

```javascript
const username = altair.helpers.getEnvironment("username");
const password = altair.helpers.getEnvironment("password");
const scope = altair.helpers.getEnvironment("scope");
let endpointUrl = altair.helpers.getEnvironment("endpointUrl");
if (endpointUrl.endsWith("/")) {
  endpointUrl = endpointUrl.substring(0, endpointUrl.length - 1);
}

if (altair.helpers.getEnvironment("doAuth")) {
  const response = await altair.helpers.request(
    "POST",
    `${endpointUrl}/api/beginsession`,
    {
      body: {
        username: username,
        password: password,
        scope: scope
      }
    }
  );
  altair.helpers.setEnvironment("token", response.authorizationResult.token);
}
```

### Test Query

```graphql
query getContacts {
  contacts {
    records {
      name
      companyName
      industry
    }
  }
}
```

### Troubleshooting: 403 Forbidden

If you get HTTP 403, add CORS settings in ProShop:

1. Hover over company name > **System Config** > **Dev** tab
2. Scroll to `allowListCORS`
3. Enter `electron://altair`

---

## 7. ProShop API Playground (v5.2.3+)

As of ProShop v5.2.3, a built-in API playground is available at:

```
https://yourco.adionsystems.com/api/graphql
```

This functions like Altair/Postman but handles authorization and scope automatically based on the logged-in ProShop user. No setup required.

---

## 8. Authorization Scopes — Quick Reference

Scopes are passed as space-delimited strings with optional permission suffixes:

```
module:permissions
```

**Permission suffixes:**

| Suffix | Meaning |
|--------|---------|
| `r`    | Read    |
| `w`    | Write   |
| `d`    | Delete  |
| `p`    | Print   |

**Examples:**

```
users:r                     # Read-only access to users
workorders:rwdp             # Full access to work orders
contacts:rw                 # Read/write access to contacts
customerpo:rwd users:r      # Multiple scopes, space-separated
```

**Modules relevant to Miltech CRM integration:**

| Scope        | Use Case |
|-------------|----------|
| `quotes`     | Read quote status and amounts |
| `customerpos` | Read PO receipt data |
| `workorders` | Read job/shipping status |
| `contacts`   | Sync customer information |
| `estimates`  | Read estimate/RFQ data |
| `invoices`   | Read actual invoiced amounts |

---

## Appendix: Miltech Integration Planning Notes

### Recommended Authentication

Use the **Client Credentials Flow** (Section 2.4) for the Odoo integration — it requires no user interaction and is designed for server-to-server communication.

### Recommended Polling Strategy

Use the **Recently Updated Records API** (Section 5) to efficiently detect changes:

1. Run a scheduled Odoo cron job every 5–15 minutes
2. Call `/recentlyupdatedrecords?start=<last_poll_time>&filterby=quotes,customerpos,workorders`
3. For each changed record, query full details via GraphQL
4. Match to Odoo CRM leads by customer name + quote/PO number
5. Update stage, revenue, and custom fields accordingly

### Key Queries to Build

```graphql
# Get quote details by number
query getQuote($num: String!) {
  quote(quoteNumber: $num) {
    quoteNumber
    status
    totalPrice
    customerName
    # ... explore schema for full field list
  }
}

# Get customer PO details
query getPO($num: String!) {
  customerPo(customerPoNumber: $num) {
    customerPoNumber
    status
    # ... explore schema for full field list
  }
}

# Get work order shipping status
query getWO($num: String!) {
  workOrder(workOrderNumber: $num) {
    workOrderNumber
    status
    shipDate
    # ... explore schema for full field list
  }
}
```

> **Note:** Exact field names must be confirmed via schema introspection using Altair or the API Playground, as the docs don't enumerate every field for every module.
