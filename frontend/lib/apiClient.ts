import { getToken, redirectToLogin } from "@/lib/auth";

// Matches frontend/.env.local.example's existing NEXT_PUBLIC_API_URL convention.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Thrown for non-401 API failures so callers can show the real reason. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Pulls the human-readable reason out of a FastAPI error body.
 *
 * FastAPI uses `detail` for both hand-written messages (a string) and
 * validation failures (an array of issues), so both shapes are handled; an
 * unparseable body falls back to the status code rather than showing raw HTML.
 */
function extractDetail(body: string, status: number): string {
  const fallback = `Request failed (${status})`;
  if (!body) return fallback;
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((issue) =>
            typeof issue === "object" && issue !== null && "msg" in issue
              ? String((issue as { msg: unknown }).msg)
              : null,
          )
          .filter((m): m is string => m !== null);
        if (messages.length > 0) return messages.join("; ");
      }
    }
  } catch {
    // Not JSON — fall through.
  }
  return fallback;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  // Every /api/* route on the backend requires a bearer token. Attaching it
  // centrally here means a newly added call cannot forget it -- the failure
  // mode that would otherwise only appear at runtime, never at build time.
  const token = getToken();

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers ?? {}),
    },
  });

  if (res.status === 401) {
    // Expired or missing session: send the user to log in rather than
    // surfacing a raw 401 that looks like a bug.
    redirectToLogin();
    throw new ApiError("Session expired. Please log in again.", 401, path);
  }

  if (!res.ok) {
    // The backend's `detail` is written for the operator and names the actual
    // problem ("'Kenwood' already exists as a brand"). Surfacing the raw JSON
    // envelope instead would bury the one sentence that says how to fix it.
    const body = await res.text().catch(() => "");
    throw new ApiError(extractDetail(body, res.status), res.status, path);
  }

  // 204 and other empty responses have no JSON body to parse.
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export type SourceMode = "strict" | "priority";

export interface SkuSnapshotStatus {
  readonly sku_count: number;
  readonly last_imported_at: string | null;
}

export interface SkuSnapshotUploadResult {
  readonly success: boolean;
  readonly count: number;
  readonly skipped_rows: number;
  readonly had_header: boolean;
  readonly warnings: readonly string[];
}

/**
 * Uploads the live-SKU export that powers the duplicate-SKU guard.
 *
 * Deliberately bypasses `request()`: multipart uploads must NOT carry a
 * `Content-Type: application/json` header, and the browser has to set the
 * multipart boundary itself.
 */
async function uploadSkuSnapshot(file: File): Promise<SkuSnapshotUploadResult> {
  const token = getToken();
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/api/settings/live-sku-snapshot`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });

  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError("Session expired. Please log in again.", 401, "/api/settings/live-sku-snapshot");
  }

  if (!res.ok) {
    // The backend's `detail` names the actual problem (wrong column, empty
    // file, too large) — surfacing it is what lets the user fix the upload.
    let detail = `Upload failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new ApiError(detail, res.status, "/api/settings/live-sku-snapshot");
  }

  return (await res.json()) as SkuSnapshotUploadResult;
}

/**
 * One row of the real input sheet:
 *   S.No | Product Name | Regular Price | Sale Price | Warranty | Status
 *
 * `price_a`/`price_b` are the two price cells IN SHEET ORDER. Which one is the
 * regular price is decided from the VALUES server-side, never from the column
 * headers — in the real sheet the "Regular Price" column holds the lower
 * selling price, so trusting the labels would publish a price rise as a
 * discount.
 */
export interface SheetRowInput {
  readonly product_name: string;
  readonly price_a: string;
  readonly price_b: string;
  // `| undefined` is explicit because exactOptionalPropertyTypes is on: an
  // absent warranty cell and a present-but-empty one must both be expressible.
  readonly warranty?: string | undefined;
  readonly status?: string | undefined;
}

export interface SheetRowPreview {
  readonly product_name: string;
  readonly sku: string | null;
  readonly model_number: string | null;
  readonly brand_name: string | null;
  readonly category_name: string | null;
  readonly category_path: string | null;
  readonly regular_price: string;
  readonly sale_price: string | null;
  readonly warranty_phrase: string | null;
  readonly template_choice: string | null;
  readonly missing_required: readonly string[];
  readonly ready: boolean;
}

export interface AuditEvent {
  readonly id: string;
  readonly created_at: string;
  readonly event_type: string;
  readonly actor: string;
  readonly product_id: string | null;
  readonly batch_id: string | null;
  readonly payload: Record<string, unknown>;
}

export interface DashboardStats {
  manual_review_count: number;
  ready_for_qa_count: number;
  batches_in_progress_count: number;
  week_approved_count: number;
  avg_qa_seconds: number | null;
}

export interface Batch {
  id: string;
  label: string;
  status: string;
  total_products: number;
  succeeded_count: number;
  failed_count: number;
  manual_review_count: number;
  created_at: string;
  updated_at: string;
}

export interface SeoCheckResult {
  check_name: string;
  passed: boolean;
  detail: string;
}

export interface ReviewResult {
  passed: boolean;
  preflight_score: number;
  checks: SeoCheckResult[];
  warranty_consistent: boolean;
  fact_cross_check_passed: boolean;
  fact_cross_check_notes: string[];
  failure_summary?: string | null;
}

export interface Product {
  id: string;
  batch_id: string;
  sku: string;
  model_number?: string | null;
  status: string;
  name?: string | null;
  short_description?: string | null;
  description?: string | null;
  specs_table_html?: string | null;
  rank_math_focus_keyword?: string | null;
  rank_math_title?: string | null;
  rank_math_description?: string | null;
  regular_price?: string | null;
  sale_price?: string | null;
  extraction_result?: Record<string, unknown>;
  review_result?: ReviewResult | null;
  // Set when the pipeline escalated instead of producing a row. These are the
  // only fields that say WHY a product is sitting in the review queue.
  failure_reason?: string | null;
  failure_detail?: { detail?: string } | null;
  queued_at?: string | null;
  retry_count?: number | null;
}

export interface SourceCitation {
  id: string;
  product_id: string;
  field_name: string;
  value: string;
  source_url: string | null;
  source_type: string;
  confidence: string;
}

export type TrustLevelMode = "full_review" | "quick_review";

export interface TaxonomyBrand {
  id: string;
  name: string;
  // Display casing for the product title only (e.g. "Haier"); the Brands column
  // keeps `name`. Null/absent means the title uses `name` as-is.
  display_name?: string | null;
  casing_confirmed: boolean;
  is_active: boolean;
}

export interface TaxonomyCategory {
  id: string;
  name: string;
  parent_id: string | null;
  is_active: boolean;
  needs_confirmation: boolean;
}

export interface RawProductInput {
  sku: string;
  model_number: string;
  brand_name: string;
  category_name: string;
  product_type: string;
  regular_price: string;
  sale_price: string;
  in_stock: boolean;
  warranty_override?: string | null;
  template_choice: "A" | "B";
}

export interface WarrantyRow {
  id: string;
  brand_name: string;
  category_name: string;
  warranty_phrase: string;
  last_audited_at: string | null;
  is_stale: boolean;
}

export interface TrustedSecondarySource {
  id: string;
  domain: string;
  label: string;
  priority: number;
  is_active: boolean;
}

export type ApiKeyStatus = Record<string, boolean>;

export interface SeoTitleDescriptors {
  category_descriptors: Record<string, string>;
  fallback_power_word: string;
}

export interface TemplateRecord {
  id: string;
  template_type: "short_description" | "long_description_a" | "long_description_b" | "specs_table";
  name: string;
  html_skeleton: string;
  is_default: boolean;
  is_active: boolean;
  version: number;
}

export const api = {
  listBrands: () => request<TaxonomyBrand[]>("/api/taxonomy/brands"),
  updateBrand: (
    id: string,
    data: Partial<{ casing_confirmed: boolean; is_active: boolean; display_name: string }>,
  ) => request<TaxonomyBrand>(`/api/taxonomy/brands/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  createCategory: (name: string, parent_id?: string) =>
    request<TaxonomyCategory>("/api/taxonomy/categories", {
      method: "POST",
      body: JSON.stringify({ name, parent_id: parent_id || null }),
    }),
  updateCategory: (
    id: string,
    data: Partial<{ parent_id: string | null; is_active: boolean; needs_confirmation: boolean; notes: string }>
  ) => request<TaxonomyCategory>(`/api/taxonomy/categories/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  listTemplates: () => request<TemplateRecord[]>("/api/templates/"),
  createTemplate: (data: { template_type: string; name: string; html_skeleton: string }) =>
    request<TemplateRecord>("/api/templates/", { method: "POST", body: JSON.stringify(data) }),
  updateTemplate: (id: string, data: Partial<{ name: string; html_skeleton: string; is_active: boolean }>) =>
    request<TemplateRecord>(`/api/templates/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  listTrustedSecondarySources: () => request<TrustedSecondarySource[]>("/api/sources/trusted-secondary"),
  addTrustedSecondarySource: (domain: string, label: string) =>
    request<TrustedSecondarySource>("/api/sources/trusted-secondary", {
      method: "POST",
      body: JSON.stringify({ domain, label }),
    }),
  toggleTrustedSecondarySource: (id: string, is_active: boolean) =>
    request<TrustedSecondarySource>(`/api/sources/trusted-secondary/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active }),
    }),
  getApiKeyStatus: () => request<ApiKeyStatus>("/api/settings/api-key-status"),
  getSeoTitleDescriptors: () => request<SeoTitleDescriptors>("/api/settings/seo-title-descriptors"),
  createBrand: (name: string) =>
    request<TaxonomyBrand>("/api/taxonomy/brands", { method: "POST", body: JSON.stringify({ name }) }),
  listCategories: () => request<TaxonomyCategory[]>("/api/taxonomy/categories"),
  listWarrantyMatrix: () => request<WarrantyRow[]>("/api/warranty/"),
  getDashboardStats: () => request<DashboardStats>("/api/dashboard/stats"),
  listBatches: () => request<Batch[]>("/api/batches/"),
  createBatch: (label: string) =>
    request<{ batch_id: string; status: string }>(`/api/batches/?label=${encodeURIComponent(label)}`, {
      method: "POST",
    }),
  getBatch: (id: string) => request<Batch>(`/api/batches/${id}`),
  runBatch: (id: string) =>
    request<{ batch_id: string; status: string }>(`/api/batches/${id}/run`, { method: "POST" }),
  listProductsByBatch: (batchId: string) => request<Product[]>(`/api/products/batch/${batchId}`),
  listProducts: (status?: string) =>
    request<Product[]>(`/api/products/${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  createBatchNoRun: (label: string) =>
    request<{ batch_id: string; status: string }>(
      `/api/batches/?label=${encodeURIComponent(label)}&auto_run=false`,
      { method: "POST" }
    ),
  createProduct: (batchId: string, rawInput: RawProductInput) =>
    request<Product>(`/api/products/?batch_id=${batchId}`, {
      method: "POST",
      body: JSON.stringify(rawInput),
    }),
  getProduct: (id: string) => request<Product>(`/api/products/${id}`),
  getProductCitations: (id: string) => request<SourceCitation[]>(`/api/products/${id}/citations`),
  updateProduct: (id: string, data: Partial<Record<string, unknown>>) =>
    request<Product>(`/api/products/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  getTrustLevel: () => request<{ mode: TrustLevelMode }>("/api/settings/trust-level"),
  setTrustLevel: (mode: TrustLevelMode) =>
    request<{ mode: TrustLevelMode }>("/api/settings/trust-level", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),

  // --- Live SKU snapshot (duplicate-SKU guard) ---
  getSkuSnapshotStatus: () =>
    request<SkuSnapshotStatus>("/api/settings/live-sku-snapshot"),
  uploadSkuSnapshot: uploadSkuSnapshot,

  // Preview only — writes nothing. Lets prices, SKUs, brands and categories be
  // checked before any product row exists.
  parseSheet: (rows: readonly SheetRowInput[]) =>
    request<SheetRowPreview[]>("/api/products/parse-sheet", {
      method: "POST",
      body: JSON.stringify(rows),
    }),

  // --- Audit trail (read-only by design; entries are written server-side) ---
  listAuditEvents: (limit = 100) =>
    request<AuditEvent[]>(`/api/audit/?limit=${limit}`),

  // --- Brand official domains (source-discovery tier 2) ---
  // Keyed by brand id. A brand absent from this map has no official source
  // configured, so tier 2 of discovery is skipped for it entirely.
  listBrandDomains: () => request<Record<string, string>>("/api/sources/brand-domains"),
  setBrandDomain: (brandId: string, officialDomain: string) =>
    request<{ official_domain: string }>(`/api/sources/brand-domains/${brandId}`, {
      method: "PUT",
      body: JSON.stringify({ official_domain: officialDomain }),
    }),
  clearBrandDomain: (brandId: string) =>
    request<void>(`/api/sources/brand-domains/${brandId}`, { method: "DELETE" }),

  reorderTrustedSecondarySources: (sourceIds: readonly string[]) =>
    request<TrustedSecondarySource[]>("/api/sources/trusted-secondary/order", {
      method: "PUT",
      body: JSON.stringify({ source_ids: sourceIds }),
    }),
  setTrustedSecondarySourcePriority: (id: string, priority: number) =>
    request<TrustedSecondarySource>(`/api/sources/trusted-secondary/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ priority }),
    }),

  // --- Source mode ---
  getSourceMode: () => request<{ mode: SourceMode }>("/api/settings/source-mode"),
  setSourceMode: (mode: SourceMode) =>
    request<{ mode: SourceMode }>("/api/settings/source-mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),
};
