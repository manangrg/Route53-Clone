"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type User = {
  id: number;
  username: string;
  name: string;
  role: string;
};

type Zone = {
  id: number;
  name: string;
  comment: string;
  zone_type: "public" | "private";
  created_at: string;
  updated_at: string;
  record_count: number;
  records: RecordItem[];
};

type RecordItem = {
  id?: number;
  name: string;
  type: string;
  ttl: number;
  value?: string | null;
  priority?: number | null;
  weight?: number | null;
  port?: number | null;
  target?: string | null;
};

type RecordPage = {
  items: RecordItem[];
  page: number;
  limit: number;
  total: number;
};

type ModalFormState = {
  zone: {
    mode: "create" | "edit" | null;
    id?: number;
    name: string;
    comment: string;
    zone_type: "public" | "private";
  };
  record: {
    mode: "create" | "edit" | null;
    id?: number;
    name: string;
    type: string;
    ttl: number;
    value: string;
    priority: string;
    weight: string;
    port: string;
  };
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";
const defaultModalState: ModalFormState = {
  zone: { mode: null, name: "", comment: "", zone_type: "public" },
  record: {
    mode: null,
    name: "",
    type: "A",
    ttl: 300,
    value: "",
    priority: "",
    weight: "",
    port: "",
  },
};

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const errorMessage = typeof data === "string" ? data : data?.detail || "Request failed";
    throw new Error(errorMessage);
  }

  return data as T;
}

type ConsoleView = "list" | "detail" | "create-zone" | "edit-zone" | "create-record";

export default function Route53Console({
  view,
  zoneId,
}: {
  view: ConsoleView;
  zoneId?: string;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [zoneDetail, setZoneDetail] = useState<Zone | null>(null);
  const [zoneTotal, setZoneTotal] = useState(0);
  const [zonePage, setZonePage] = useState(1);
  const [zonePageSize, setZonePageSize] = useState(10);
  const [selectedZoneId, setSelectedZoneId] = useState<number | null>(
    zoneId && Number.isInteger(Number(zoneId)) ? Number(zoneId) : null,
  );
  const [recordList, setRecordList] = useState<RecordItem[]>([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [recordPage, setRecordPage] = useState(1);
  const [recordPageSize, setRecordPageSize] = useState(25);
  const [recordSearch, setRecordSearch] = useState("");
  const [recordTypeFilter, setRecordTypeFilter] = useState("");
  const [selectedRecordIds, setSelectedRecordIds] = useState<number[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [authLoading, setAuthLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [darkMode, setDarkMode] = useState(false);
  const [activeSection, setActiveSection] = useState("Hosted Zones");
  const [consoleSearch, setConsoleSearch] = useState("");
  const [selectedRegion, setSelectedRegion] = useState("Global");
  const [formState, setFormState] = useState<ModalFormState>(() => ({
    ...defaultModalState,
    zone: {
      ...defaultModalState.zone,
      mode: view === "create-zone" ? "create" : view === "edit-zone" ? "edit" : null,
    },
    record: {
      ...defaultModalState.record,
      mode: view === "create-record" ? "create" : null,
    },
  }));
  const [importText, setImportText] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const consoleSearchInput = useRef<HTMLInputElement>(null);
  const consoleBarRef = useRef<HTMLDivElement>(null);

  const selectedZone = zoneDetail ?? (selectedZoneId !== null ? zones.find((zone) => zone.id === selectedZoneId) ?? null : null);

  useEffect(() => {
    document.body.classList.toggle("dark-mode", darkMode);
  }, [darkMode]);

  useEffect(() => {
    const closeMenusOnOutsideClick = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || target.closest(".console-menu")) return;
      consoleBarRef.current
        ?.querySelectorAll<HTMLDetailsElement>(".console-menu[open]")
        .forEach((menu) => {
          menu.open = false;
        });
    };

    document.addEventListener("pointerdown", closeMenusOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeMenusOnOutsideClick);
  }, []);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search).get("search") ?? "";
    // Keep the console search controls in sync when a hosted-zone URL carries a search query.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setConsoleSearch(query);
    setSearchTerm(query);
  }, []);

  const loadZones = async () => {
    try {
      const params = new URLSearchParams({
        search: searchTerm,
        page: String(zonePage),
        limit: String(zonePageSize),
      });
      const data = await apiFetch<{ items: Zone[]; total: number }>(`/api/hosted-zones?${params}`);
      setZones(data.items);
      setZoneTotal(data.total);
      setError(null);
      if (!data.items.some((zone) => zone.id === selectedZoneId)) {
        setSelectedZoneId(data.items[0]?.id ?? null);
      }
    } catch {
      setError("Unable to load hosted zones.");
    }
  };

  const loadZoneDetail = async (id: number) => {
    try {
      const zone = await apiFetch<Zone>(`/api/hosted-zones/${id}`);
      setZoneDetail(zone);
      setSelectedZoneId(id);
      setError(null);
      if (view === "edit-zone") {
        setFormState((current) => ({
          ...current,
          zone: {
            ...current.zone,
            name: zone.name,
            comment: zone.comment || "",
            zone_type: zone.zone_type,
          },
        }));
      }
    } catch (err) {
      setZoneDetail(null);
      setError(err instanceof Error ? err.message : "Unable to load hosted zone.");
    }
  };

  const loadRecords = async (zoneId: number) => {
    try {
      const params = new URLSearchParams({
        search: recordSearch,
        type: recordTypeFilter,
        page: String(recordPage),
        limit: String(recordPageSize),
      });
      const data = await apiFetch<RecordPage>(`/api/hosted-zones/${zoneId}/records?${params}`);
      setRecordList(data.items);
      setRecordTotal(data.total);
      setSelectedRecordIds([]);
    } catch {
      setError("Unable to load DNS records.");
    }
  };

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const response = await apiFetch<{ user: User }>('/api/auth/me');
        setUser(response.user);
        await loadZones();
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    };
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (zoneId && user && Number.isInteger(Number(zoneId))) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadZoneDetail(Number(zoneId));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoneId, user]);

  useEffect(() => {
    if (user && selectedZoneId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadRecords(selectedZoneId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, selectedZoneId, recordSearch, recordTypeFilter, recordPage, recordPageSize]);

  useEffect(() => {
    if (user) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadZones();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, searchTerm, zonePage, zonePageSize]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        consoleSearchInput.current?.focus();
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "/") {
        event.preventDefault();
        searchInput.current?.focus();
      } else if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        router.push("/hosted-zones/create");
      } else if (event.key.toLowerCase() === "r" && selectedZoneId) {
        event.preventDefault();
        router.push(`/hosted-zones/${selectedZoneId}/create-record`);
      } else if (event.key === "Escape") {
        if (view === "detail" || view === "create-record" || view === "edit-zone") {
          router.push(`/hosted-zones/${zoneId}`);
        } else if (view === "create-zone") {
          router.push("/hosted-zones");
        } else {
          setFormState(defaultModalState);
        }
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [router, selectedZoneId, view, zoneId]);

  const login = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAuthLoading(true);
    setError(null);

    const formData = new FormData(event.currentTarget);
    const username = String(formData.get("username") || "");
    const password = String(formData.get("password") || "");

    try {
      const response = await apiFetch<{ user: User }>('/api/auth/login', {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setUser(response.user);
      setSelectedZoneId(null);
      await loadZones();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
      setUser(null);
      setZones([]);
      setRecordList([]);
      setSelectedZoneId(null);
      setZoneDetail(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Logout failed");
    }
  };

  const openCreateZoneModal = () => {
    setError(null);
    router.push("/hosted-zones/create");
  };

  const searchHostedZones = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = consoleSearch.trim();
    setConsoleSearch(query);
    setSearchTerm(query);
    setZonePage(1);
    setError(null);
    setActiveSection("Hosted Zones");
    router.push(query ? `/hosted-zones?search=${encodeURIComponent(query)}` : "/hosted-zones");
  };

  const goToHostedZones = () => {
    setError(null);
    setActiveSection("Hosted Zones");
    setConsoleSearch("");
    setSearchTerm("");
    setZonePage(1);
    router.push("/hosted-zones");
  };

  const openEditZoneModal = (zone: Zone) => {
    setError(null);
    router.push(`/hosted-zones/${zone.id}/edit`);
  };

  const openCreateRecordModal = () => {
    if (selectedZoneId) {
      setError(null);
      router.push(`/hosted-zones/${selectedZoneId}/create-record`);
    }
  };

  const openEditRecordModal = (record: RecordItem) => {
    setFormState({
      ...defaultModalState,
      record: {
        mode: "edit",
        id: record.id,
        name: record.name,
        type: record.type,
        ttl: record.ttl,
        value: record.value || "",
        priority: record.priority?.toString() || "",
        weight: record.weight?.toString() || "",
        port: record.port?.toString() || "",
      },
    });
  };

  const submitZone = async (event: React.FormEvent) => {
    event.preventDefault();
    const zoneName = formState.zone.name || (view === "edit-zone" ? selectedZone?.name ?? "" : "");
    const comment = formState.zone.comment || (view === "edit-zone" ? selectedZone?.comment ?? "" : "");
    const zoneType = view === "edit-zone"
      ? selectedZone?.zone_type ?? "public"
      : formState.zone.zone_type || "public";
    if (!zoneName.trim()) {
      setError("Hosted zone name is required.");
      return;
    }

    try {
      if (view === "edit-zone" && zoneId) {
        const updated = await apiFetch<Zone>(`/api/hosted-zones/${zoneId}`, {
          method: "PUT",
          body: JSON.stringify({
            name: zoneName,
            comment,
            zone_type: zoneType,
          }),
        });
        await loadZones();
        router.push(`/hosted-zones/${updated.id}`);
      } else {
        const created = await apiFetch<Zone>('/api/hosted-zones', {
          method: "POST",
          body: JSON.stringify({
            name: zoneName,
            comment,
            zone_type: zoneType,
          }),
        });
        await loadZones();
        router.push(`/hosted-zones/${created.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save hosted zone.");
    }
  };

  const submitRecord = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedZoneId) {
      setError("Choose a hosted zone first.");
      return;
    }

    const body = {
      name: formState.record.name,
      type: formState.record.type,
      ttl: Number(formState.record.ttl || 300),
      value: formState.record.value || undefined,
      priority: formState.record.priority ? Number(formState.record.priority) : undefined,
      weight: formState.record.weight ? Number(formState.record.weight) : undefined,
      port: formState.record.port ? Number(formState.record.port) : undefined,
    };

    try {
      if (formState.record.mode === "edit" && formState.record.id) {
        await apiFetch(`/api/hosted-zones/${selectedZoneId}/records/${formState.record.id}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      } else {
        await apiFetch(`/api/hosted-zones/${selectedZoneId}/records`, {
          method: "POST",
          body: JSON.stringify(body),
        });
      }
      setFormState(defaultModalState);
      await loadRecords(selectedZoneId);
      await loadZones();
      if (view === "create-record") router.push(`/hosted-zones/${selectedZoneId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save DNS record.");
    }
  };

  const deleteZone = async (zoneId: number) => {
    const zone = zones.find((item) => item.id === zoneId) ?? zoneDetail;
    if (!window.confirm(`Delete hosted zone ${zone?.name ?? "this zone"} and all of its records?`)) return;
    try {
      await apiFetch(`/api/hosted-zones/${zoneId}`, { method: "DELETE" });
      if (selectedZoneId === zoneId) {
        setSelectedZoneId(null);
        setZoneDetail(null);
        router.push("/hosted-zones");
      }
      await loadZones();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete hosted zone.");
    }
  };

  const deleteRecord = async (recordId: number) => {
    if (!selectedZoneId) return;
    if (!window.confirm("Delete this DNS record?")) return;
    try {
      await apiFetch(`/api/hosted-zones/${selectedZoneId}/records/${recordId}`, { method: "DELETE" });
      await loadRecords(selectedZoneId);
      await loadZones();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete record.");
    }
  };

  const bulkDeleteRecords = async () => {
    if (!selectedZoneId || selectedRecordIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedRecordIds.length} selected record(s)?`)) return;
    try {
      await apiFetch(`/api/hosted-zones/${selectedZoneId}/records/bulk-delete`, {
        method: "POST",
        body: JSON.stringify({ record_ids: selectedRecordIds }),
      });
      setSelectedRecordIds([]);
      await loadRecords(selectedZoneId);
      await loadZones();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk delete failed.");
    }
  };

  const toggleRecordSelection = (recordId: number) => {
    setSelectedRecordIds((current) =>
      current.includes(recordId) ? current.filter((id) => id !== recordId) : [...current, recordId],
    );
  };

  const setPageSize = (size: number) => {
    setRecordPageSize(size);
    setRecordPage(1);
  };

  const exportZone = async (zone: Zone, format: "json" | "bind" = "json") => {
    try {
      const response = await fetch(`${API_URL}/api/hosted-zones/${zone.id}/export?fmt=${format}`, {
        credentials: "include",
      });
      if (!response.ok) {
        const message = response.headers.get("content-type")?.includes("application/json")
          ? (await response.json()).detail
          : await response.text();
        throw new Error(message || "Export failed.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${zone.name.replace(/\.$/, "")}.${format === "bind" ? "zone" : "json"}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
    }
  };

  const importZone = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedZoneId) return;
    try {
      await apiFetch(`/api/hosted-zones/${selectedZoneId}/import`, {
        method: "POST",
        body: JSON.stringify({ content: importText }),
      });
      setImportText("");
      await loadRecords(selectedZoneId);
      await loadZones();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    }
  };

  if (loading) {
    return <div className="page-loading">Loading Route53 Console...</div>;
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <div className="auth-container">
          <div className="auth-brand">
            <span className="auth-brand-mark" aria-hidden="true">
              <svg viewBox="0 0 36 36" fill="none">
                <path d="M8 25.5 17.8 10l10.2 15.5" />
                <circle cx="8" cy="26" r="3" />
                <circle cx="18" cy="10" r="3" />
                <circle cx="28" cy="26" r="3" />
              </svg>
            </span>
            <span>Route 53</span>
            <span className="auth-brand-divider" aria-hidden="true" />
            <span className="auth-brand-caption">DNS console</span>
          </div>
          <div className="auth-layout">
            <section className="auth-card" aria-labelledby="sign-in-title">
              <p className="auth-eyebrow">Console access</p>
              <h1 id="sign-in-title">Sign in</h1>
              <p className="auth-intro">Access your hosted zones and DNS records.</p>
              <div className="auth-account-type">
                <span className="auth-radio" aria-hidden="true"><span /></span>
                <span>
                  <strong>Demo account</strong>
                  <small>Assignment environment access</small>
                </span>
              </div>
              {error ? <div className="alert error" role="alert">{error}</div> : null}
              <form onSubmit={login} className="auth-form">
                <label>
                  Username
                  <input name="username" autoComplete="username" defaultValue="admin" required />
                </label>
                <label>
                  Password
                  <input name="password" type="password" autoComplete="current-password" defaultValue="admin123" required />
                </label>
                <button type="submit" disabled={authLoading}>
                  {authLoading ? "Signing in..." : "Continue"}
                </button>
              </form>
              <p className="auth-demo-note">Demo credentials: <strong>admin</strong> / <strong>admin123</strong></p>
            </section>
            <aside className="auth-promo">
              <div className="auth-promo-lines" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div className="auth-promo-content">
                <p className="auth-promo-kicker">DNS MANAGEMENT</p>
                <h2>Keep your domains in view.</h2>
                <p>Manage hosted zones and the records that connect your services.</p>
                <div className="auth-feature-list">
                  <span><i aria-hidden="true">01</i> Hosted zones</span>
                  <span><i aria-hidden="true">02</i> DNS record sets</span>
                  <span><i aria-hidden="true">03</i> Zone import &amp; export</span>
                </div>
              </div>
              <span className="auth-promo-orbit auth-promo-orbit-one" aria-hidden="true" />
              <span className="auth-promo-orbit auth-promo-orbit-two" aria-hidden="true" />
            </aside>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="aws-pill">AWS</div>
          <div>
            <div className="sidebar-title">Route53</div>
            <small>DNS management</small>
          </div>
        </div>

        <nav className="nav-list">
          {[
            "Dashboard",
            "Hosted Zones",
            "Traffic Policies",
            "Health Checks",
            "Resolver",
            "Profiles",
          ].map((item) => (
            <button
              key={item}
              className={`nav-item ${item === activeSection ? "active" : ""}`}
              type="button"
              onClick={() => {
                if (item === "Hosted Zones") {
                  goToHostedZones();
                  return;
                }
                setActiveSection(item);
                setError(null);
              }}
            >
              {item}
            </button>
          ))}
        </nav>
      </aside>

      <section className="content-shell">
        <div className="console-bar" ref={consoleBarRef}>
          <div className="console-brand"><span className="aws-wordmark">aws</span><span>Console</span></div>
          <form className="console-search" onSubmit={searchHostedZones} role="search">
            <span aria-hidden="true">⌕</span>
            <input
              ref={consoleSearchInput}
              aria-label="Search hosted zones"
              value={consoleSearch}
              onChange={(event) => setConsoleSearch(event.target.value)}
              placeholder="Search hosted zones"
            />
            <button type="submit" aria-label="Submit hosted zone search"><kbd>⌘ K</kbd></button>
          </form>
          <div className="console-context">
            <details className="console-menu" name="console-menu">
              <summary aria-label={`Region: ${selectedRegion}`}><span aria-hidden="true">◉</span> {selectedRegion}</summary>
              <div className="console-menu-popover region-menu">
                <strong>Console scope</strong>
                {["Global", "US East (N. Virginia)", "Europe (Ireland)"].map((region) => (
                  <button
                    key={region}
                    type="button"
                    className={selectedRegion === region ? "selected" : ""}
                    onClick={() => setSelectedRegion(region)}
                  >
                    {region}
                  </button>
                ))}
                <small>Display preference only; demo data is shared.</small>
              </div>
            </details>
            <details className="console-menu" name="console-menu">
              <summary aria-label="Notifications">◉</summary>
              <div className="console-menu-popover notification-menu">
                <strong>Notifications</strong>
                <p>You’re all caught up. There are no new notifications.</p>
              </div>
            </details>
            <details className="console-menu account-menu" name="console-menu">
              <summary>{user.username} <span aria-hidden="true">▾</span></summary>
              <div className="console-menu-popover account-menu-popover">
                <div className="account-menu-identity">
                  <strong>{user.name}</strong>
                  <small>{user.username} · {user.role}</small>
                </div>
                <button type="button" onClick={() => setDarkMode((previous) => !previous)}>
                  {darkMode ? "Switch to light mode" : "Switch to dark mode"}
                </button>
                <button type="button" className="account-menu-signout" onClick={logout}>Sign out</button>
              </div>
            </details>
          </div>
        </div>
        <header className="topbar">
          <div>
            <nav className="breadcrumbs" aria-label="Breadcrumb">
              <Link href="/hosted-zones" onClick={goToHostedZones}>Services</Link>
              <span aria-hidden="true">›</span>
              <Link href="/hosted-zones" onClick={goToHostedZones}>Networking &amp; Content Delivery</Link>
              <span aria-hidden="true">›</span>
              <Link href="/hosted-zones" onClick={goToHostedZones}>Route 53</Link>
            </nav>
            <h1>
              {view === "create-zone" ? "Create hosted zone"
                : view === "edit-zone" ? "Edit hosted zone"
                  : view === "create-record" ? "Create record"
                    : view === "detail" ? selectedZone?.name || "Hosted zone details"
                      : "Hosted zones"}
            </h1>
          </div>
        </header>

        {error ? <div className="alert error">{error}</div> : null}

        {activeSection === "Hosted Zones" && view === "list" ? <div className="card main-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Amazon Route 53</p>
              <h2>Hosted zones <span className="count-badge">{zoneTotal}</span></h2>
              <p className="panel-description">Choose a hosted zone to view and manage its DNS records, including A, AAAA, CNAME, MX, TXT, and more.</p>
            </div>
            <div className="header-actions">
              <button type="button" className="secondary-button" onClick={() => searchInput.current?.focus()}>
                Search <kbd>/</kbd>
              </button>
              <button type="button" className="primary-button" onClick={openCreateZoneModal}>
                Create hosted zone
              </button>
            </div>
          </div>

          <div className="toolbar">
            <input
              ref={searchInput}
              aria-label="Search hosted zones"
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setConsoleSearch(e.target.value);
                setZonePage(1);
              }}
              placeholder="Search hosted zones by domain name"
            />
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Hosted zone name</th>
                  <th>Type</th>
                  <th>Record count</th>
                  <th>Created</th>
                  <th>Comment</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((zone) => (
                  <tr
                    key={zone.id}
                    className={selectedZoneId === zone.id ? "selected-row" : ""}
                    onClick={() => {
                      setError(null);
                      setSelectedZoneId(zone.id);
                      setZoneDetail(zone);
                      setRecordPage(1);
                      router.push(`/hosted-zones/${zone.id}`);
                    }}
                  >
                    <td>
                      <strong>{zone.name}</strong>
                    </td>
                    <td><span className="status-pill">{zone.zone_type === "private" ? "Private hosted zone" : "Public hosted zone"}</span></td>
                    <td>{zone.record_count}</td>
                    <td>{new Date(zone.created_at).toLocaleDateString()}</td>
                    <td>{zone.comment || "—"}</td>
                    <td>
                      <div className="inline-actions" onClick={(e) => e.stopPropagation()}>
                        <button type="button" onClick={() => openEditZoneModal(zone)}>
                          Edit
                        </button>
                        <button type="button" className="danger-ghost" onClick={() => deleteZone(zone.id)}>
                          Delete
                        </button>
                        <button type="button" onClick={() => exportZone(zone, "json")}>
                          Export JSON
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination-bar">
            <span>Showing {zoneTotal === 0 ? 0 : (zonePage - 1) * zonePageSize + 1}–{Math.min(zonePage * zonePageSize, zoneTotal)} of {zoneTotal} hosted zones</span>
            <div className="pagination-controls">
              <label>Rows per page
                <select value={zonePageSize} onChange={(e) => { setZonePageSize(Number(e.target.value)); setZonePage(1); }}>
                  {[10, 25, 50].map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
              </label>
              <button type="button" className="page-button" disabled={zonePage <= 1} onClick={() => setZonePage((page) => page - 1)}>‹</button>
              <span>Page {zonePage} of {Math.max(1, Math.ceil(zoneTotal / zonePageSize))}</span>
              <button type="button" className="page-button" disabled={zonePage >= Math.ceil(zoneTotal / zonePageSize)} onClick={() => setZonePage((page) => page + 1)}>›</button>
            </div>
          </div>
        </div> : null}

        {activeSection === "Hosted Zones" && view === "detail" && selectedZone ? (
          <div className="card record-panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">DNS records · A · AAAA · CNAME · MX · TXT · and more</p>
                <h2>{selectedZone.name}</h2>
              </div>
              <div className="header-actions">
                <button type="button" className="secondary-button" onClick={() => openEditZoneModal(selectedZone)}>
                  Edit zone
                </button>
                <button type="button" className="secondary-button" onClick={() => exportZone(selectedZone, "bind")}>
                  Export BIND
                </button>
                <button type="button" className="primary-button" onClick={openCreateRecordModal}>
                  Create record <kbd>R</kbd>
                </button>
              </div>
            </div>

            <div className="zone-summary">
              <div><span>Hosted zone ID</span><strong>{selectedZone.id}</strong></div>
              <div><span>Type</span><strong>{selectedZone.zone_type === "private" ? "Private hosted zone" : "Public hosted zone"}</strong></div>
              <div><span>Description</span><strong>{selectedZone.comment || "—"}</strong></div>
            </div>

            <div className="record-toolbar">
              <input
                aria-label="Search DNS records"
                value={recordSearch}
                onChange={(e) => { setRecordSearch(e.target.value); setRecordPage(1); }}
                placeholder="Filter records by name or value"
              />
              <label>Record type
                <select value={recordTypeFilter} onChange={(e) => { setRecordTypeFilter(e.target.value); setRecordPage(1); }}>
                  <option value="">All types</option>
                  {["A", "AAAA", "CNAME", "TXT", "MX", "NS", "PTR", "SRV", "CAA"].map((type) => <option key={type} value={type}>{type}</option>)}
                </select>
              </label>
              {selectedRecordIds.length > 0 ? (
                <button type="button" className="danger-button" onClick={bulkDeleteRecords}>Delete selected ({selectedRecordIds.length})</button>
              ) : null}
            </div>

            <form onSubmit={importZone} className="import-box">
              <div className="import-inputs">
                <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder="Paste BIND zone data or choose a .zone/.bind file"
                />
                <label className="file-picker">Choose zone file
                  <input
                    type="file"
                    accept=".zone,.bind,.txt,text/plain"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      try {
                        setImportText(await file.text());
                      } catch (err) {
                        setError(err instanceof Error ? err.message : "Unable to read the selected zone file.");
                      }
                    }}
                  />
                </label>
              </div>
              <button type="submit" className="secondary-button">Import records</button>
            </form>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th><input type="checkbox" aria-label="Select all visible records" checked={recordList.length > 0 && recordList.every((record) => record.id && selectedRecordIds.includes(record.id))} onChange={(e) => setSelectedRecordIds(e.target.checked ? recordList.flatMap((record) => record.id ? [record.id] : []) : [])} /></th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>TTL</th>
                    <th>Value</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {recordList.map((record) => (
                    <tr key={record.id ?? `${record.name}-${record.type}`}>
                      <td><input type="checkbox" aria-label={`Select ${record.name} ${record.type}`} checked={record.id ? selectedRecordIds.includes(record.id) : false} onChange={() => record.id && toggleRecordSelection(record.id)} /></td>
                      <td>{record.name}</td>
                      <td>{record.type}</td>
                      <td>{record.ttl}</td>
                      <td>
                        {record.type === "MX"
                          ? `${record.priority} ${record.value || record.target || ""}`
                          : record.type === "SRV"
                            ? `${record.priority} ${record.weight} ${record.port} ${record.target || record.value || ""}`
                            : record.value || record.target || "—"}
                      </td>
                      <td>
                        <div className="inline-actions">
                          <button type="button" onClick={() => openEditRecordModal(record)}>
                            Edit
                          </button>
                          <button type="button" className="danger-ghost" onClick={() => deleteRecord(record.id || 0)}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {recordList.length === 0 ? (
                    <tr><td colSpan={6} className="empty-state">No records match these filters.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
            <div className="pagination-bar">
              <span>Showing {recordTotal === 0 ? 0 : (recordPage - 1) * recordPageSize + 1}–{Math.min(recordPage * recordPageSize, recordTotal)} of {recordTotal} records</span>
              <div className="pagination-controls">
                <label>Rows per page
                  <select value={recordPageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                    {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
                  </select>
                </label>
                <button type="button" className="page-button" disabled={recordPage <= 1} onClick={() => setRecordPage((page) => page - 1)}>‹</button>
                <span>Page {recordPage} of {Math.max(1, Math.ceil(recordTotal / recordPageSize))}</span>
                <button type="button" className="page-button" disabled={recordPage >= Math.ceil(recordTotal / recordPageSize)} onClick={() => setRecordPage((page) => page + 1)}>›</button>
              </div>
            </div>
          </div>
        ) : null}

        {activeSection !== "Hosted Zones" ? (
          <div className="card coming-soon">
            <p className="eyebrow">Amazon Route 53</p>
            <h2>{activeSection}</h2>
            <p>This area is a placeholder in this Route 53 demo.</p>
            <button type="button" className="secondary-button" onClick={goToHostedZones}>
              Return to hosted zones
            </button>
          </div>
        ) : null}

      {formState.zone.mode && activeSection === "Hosted Zones" ? (
        <div
          className={view === "create-zone" || view === "edit-zone" ? "route-form" : "modal-backdrop"}
          onClick={() => {
            if (view !== "create-zone" && view !== "edit-zone") setFormState(defaultModalState);
          }}
        >
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>{view === "edit-zone" ? "Edit hosted zone" : "Create hosted zone"}</h3>
            <form onSubmit={submitZone} className="modal-form">
              <label>
                Domain name
                <input
                  value={formState.zone.name || (view === "edit-zone" ? selectedZone?.name ?? "" : "")}
                  onChange={(e) => setFormState((prev) => ({ ...prev, zone: { ...prev.zone, name: e.target.value } }))}
                  disabled={view === "edit-zone"}
                  placeholder="example.com"
                />
              </label>
              {view === "edit-zone" ? <p className="form-help">Hosted zone names are immutable. Create another zone to use a different domain.</p> : null}
              {view === "create-zone" ? (
                <label>
                  Hosted zone type
                  <select
                    value={formState.zone.zone_type}
                    onChange={(e) => setFormState((prev) => ({
                      ...prev,
                      zone: { ...prev.zone, zone_type: e.target.value as "public" | "private" },
                    }))}
                  >
                    <option value="public">Public hosted zone</option>
                    <option value="private">Private hosted zone (mock; no VPC association)</option>
                  </select>
                </label>
              ) : null}
              <label>
                Comment
                <input
                  value={formState.zone.comment}
                  onChange={(e) => setFormState((prev) => ({ ...prev, zone: { ...prev.zone, comment: e.target.value } }))}
                  placeholder="Optional description"
                />
              </label>
              <div className="modal-actions">
                <button type="button" className="ghost-button" onClick={() => {
                  setError(null);
                  router.push(view === "edit-zone" && zoneId ? `/hosted-zones/${zoneId}` : "/hosted-zones");
                }}>
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  {view === "edit-zone" ? "Save changes" : "Create hosted zone"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {formState.record.mode && activeSection === "Hosted Zones" ? (
        <div
          className={view === "create-record" ? "route-form" : "modal-backdrop"}
          onClick={() => {
            if (view !== "create-record") setFormState(defaultModalState);
          }}
        >
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>{view === "create-record" ? `Create record in ${selectedZone?.name ?? "hosted zone"}` : "Edit DNS record"}</h3>
            <form onSubmit={submitRecord} className="modal-form">
              <label>
                Name
                <input
                  value={formState.record.name}
                  onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, name: e.target.value } }))}
                  placeholder="www"
                />
              </label>
              <div className="two-column-grid">
                <label>
                  Type
                  <select
                    value={formState.record.type}
                    onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, type: e.target.value } }))}
                  >
                    {['A','AAAA','CNAME','TXT','MX','NS','PTR','SRV','CAA'].map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>
                </label>
                <label>
                  TTL
                  <input
                    type="number"
                    value={formState.record.ttl}
                    onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, ttl: Number(e.target.value) } }))}
                  />
                </label>
              </div>
              <label>
                {["CNAME", "MX", "NS", "PTR", "SRV"].includes(formState.record.type) ? "Target" : "Record value"}
                <input
                  value={formState.record.value}
                  onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, value: e.target.value } }))}
                  placeholder={
                    formState.record.type === "CAA" ? '0 issue "letsencrypt.org"'
                      : formState.record.type === "TXT" ? "Enter text value"
                        : formState.record.type === "A" ? "192.0.2.10"
                          : formState.record.type === "AAAA" ? "2001:db8::1"
                            : "target.example.com"
                  }
                />
              </label>
              {["MX", "SRV"].includes(formState.record.type) ? <div className={formState.record.type === "SRV" ? "two-column-grid" : ""}>
                <label>
                  Priority
                  <input
                    type="number"
                    value={formState.record.priority}
                    onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, priority: e.target.value } }))}
                  />
                </label>
                {formState.record.type === "SRV" ? <>
                  <label>
                    Weight
                    <input
                      type="number"
                      value={formState.record.weight}
                      onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, weight: e.target.value } }))}
                    />
                  </label>
                  <label>
                    Port
                    <input
                      type="number"
                      value={formState.record.port}
                      onChange={(e) => setFormState((prev) => ({ ...prev, record: { ...prev.record, port: e.target.value } }))}
                    />
                  </label>
                </> : null}
              </div> : null}
              <div className="modal-actions">
                <button type="button" className="ghost-button" onClick={() => {
                  setFormState(defaultModalState);
                  if (view === "create-record" && zoneId) {
                    setError(null);
                    router.push(`/hosted-zones/${zoneId}`);
                  }
                }}>
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  {view === "create-record" ? "Create record" : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
      </section>
    </main>
  );
}
