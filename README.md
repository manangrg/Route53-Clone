# AWS Route 53 Clone

A full-stack recreation of core Route 53 hosted-zone and DNS-record workflows,
built as a Scaler full-stack assignment. The project combines a Next.js console
frontend with a FastAPI API and SQLite persistence. It is a learning/demo
application: it does not provision AWS resources or resolve DNS.

> **Assignment:** AWS Route 53 Clone
>
> **Frontend:** Next.js + TypeScript
>
> **Backend:** FastAPI + Python
> **Database:** SQLite

---

## Live demo

- **Application:** <https://route53-scaler-console.vercel.app>
- **Backend health:** <https://route53-api-production.up.railway.app/api/health>

The frontend is deployed to Vercel. The backend is deployed to Railway with
SQLite stored on a persistent volume. Vercel proxies `/api/*` requests to the
backend so browser authentication cookies remain same-origin.

---

## Demo credentials

```text
Username: admin
Password: admin123
```

These seeded credentials are for assignment evaluation and local demos only.
Do not use them for a production service.

---

## Overview

The application focuses on two core Route 53 resources:

1. **Hosted zones**
2. **DNS records**

```text
Sign in
  -> Search and browse hosted zones
  -> Create, edit, or delete a zone
  -> Open zone details
  -> Search, filter, and paginate DNS records
  -> Create, edit, delete, or bulk-delete records
  -> Import or export zone data
```

The UI uses AWS-console-inspired navigation and workflow patterns. The
comparison archive informed high-level architecture and UX decisions only; its
source code and assets were not copied.

---

## Features

### Authentication

- Mock login and logout
- HTTP-only session cookie backed by SQLite sessions
- Session restoration through `GET /api/auth/me`
- Salted PBKDF2 password hashes
- Startup migration of legacy plaintext password rows

This lightweight demo authentication is not intended to replace a production
identity provider.

### Hosted-zone management

- List, detail, create, and edit routes
- Create, update, and delete hosted zones
- Public and mock-private zone types
- Search and server-side pagination
- Export zone records as JSON or BIND-style text

Private zones are represented in application data only; VPC associations are
not implemented.

### DNS-record management

- Record types: A, AAAA, CNAME, TXT, MX, NS, PTR, SRV, and CAA
- Create, edit, delete, and bulk-delete records
- Search, record-type filtering, and server-side pagination
- BIND zone-file import
- Validation for DNS names, IPv4/IPv6 values, TTLs, and common type-specific
  fields
- CNAME apex and coexistence checks

The validation implements common DNS constraints, not the full DNS standards.

### Console experience

- Shared console navigation, breadcrumbs, and page chrome
- Dark mode
- Keyboard shortcuts: `/` focuses hosted-zone search, `N` opens zone creation,
  `R` opens record creation, and `Esc` leaves or closes the current workflow
- UI placeholders for out-of-scope Route 53 sections

---

## Project structure

```text
backend/
  app/
    database.py             # SQLite connection, schema, seed, and migrations
    main.py                 # FastAPI app, authentication, and resource APIs
  tests/
    test_auth_passwords.py
    test_dns_semantics.py
  .env.example
  Procfile
  requirements.txt
frontend/
  app/
    hosted-zones/            # list, detail, create, edit, and record routes
  components/
    Route53Console.tsx       # shared Route 53 console interface
  next.config.ts             # Vercel-to-API rewrite
  package.json
  package-lock.json
.gitignore
README.md
```

The local SQLite database, Python/Node dependencies, generated build output,
environment files, assignment PDF, and comparison ZIP are excluded from Git.

---

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API initializes `backend/route53.db` on startup and creates sample zones
when the database is empty.

### Frontend

In a separate terminal:

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000> and sign in with the demo credentials.
`NEXT_PUBLIC_API_URL` is the API origin, without an `/api` suffix. When this
variable is unset, the frontend uses the rewrite configured in
[`next.config.ts`](./frontend/next.config.ts), whose local target defaults to
`http://localhost:8000`.

### Tests and checks

```bash
cd frontend
npm run lint
npm run build
```

```bash
cd backend
python -m unittest discover -s tests -v
```

---

## Deployment

The current live setup uses Vercel for the Next.js frontend and Railway for the
FastAPI backend.

### Railway API

Deploy `backend/` as a Railway service. The included `Procfile` starts Uvicorn
on Railway's assigned `PORT`. Attach a persistent volume at `/data` and set:

```text
ROUTE53_DB_PATH=/data/route53.db
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
FRONTEND_ORIGINS=https://your-project.vercel.app
```

[`backend/.env.example`](./backend/.env.example) contains the same variables
with the current example Vercel origin.

### Vercel frontend

Set the project root to `frontend` and add this server-side environment
variable:

```text
API_SERVER_ORIGIN=https://your-service.up.railway.app
```

Redeploy after setting the value. The Next.js rewrite proxies API calls through
the frontend domain. The comparison ZIP must remain outside the deployment
root; it is ignored by the repository-level `.gitignore`.

---

## Database and API

SQLite persists:

| Table | Purpose |
| --- | --- |
| `users` | Demo user accounts and salted password hashes |
| `sessions` | Authenticated session tokens |
| `hosted_zones` | Zone name, type, comment, owner, and timestamps |
| `dns_records` | DNS names, types, TTLs, values, and type-specific fields |

### Authentication

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### Hosted zones

- `GET /api/hosted-zones` — supports `search`, `page`, and `limit`
- `POST /api/hosted-zones`
- `GET /api/hosted-zones/{zone_id}`
- `PUT /api/hosted-zones/{zone_id}`
- `DELETE /api/hosted-zones/{zone_id}`

### DNS records

- `GET /api/hosted-zones/{zone_id}/records` — supports `search`, `type`,
  `page`, and `limit`
- `POST /api/hosted-zones/{zone_id}/records`
- `PUT /api/hosted-zones/{zone_id}/records/{record_id}`
- `DELETE /api/hosted-zones/{zone_id}/records/{record_id}`
- `POST /api/hosted-zones/{zone_id}/records/bulk-delete`

### Import and export

- `POST /api/hosted-zones/{zone_id}/import`
- `GET /api/hosted-zones/{zone_id}/export?fmt=json|bind`

---

## Scope and originality

This is an original AWS-inspired recreation, not a pixel-perfect copy of the
AWS console. The reference project was consulted for high-level workflow and
architecture comparisons only; its source files, text, and visual assets were
not copied.

The application does not provide authoritative DNS, DNS resolution or
propagation, DNSSEC, hosted-zone delegation, private-zone VPC association, or
AWS service integration. The demo account and authentication flow are not
production-ready.
