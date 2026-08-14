import { apiFetch } from "./client";
import type { ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OrderItem {
  item_type: string;
  item_id: string;
  item_name: string;
  plan_type: string | null;
  amount: number;
}

export interface OrderRecord {
  order_id: string;
  status: string;
  total_amount: number;
  payment_source: string;
  created_at: string;
  paid_at: string | null;
  items: OrderItem[];
}

export interface OrdersResponse {
  list: OrderRecord[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    total_pages: number;
  };
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** List user orders with optional status filter and pagination. */
export function listOrders(params?: {
  status?: string;
  page?: number;
  limit?: number;
}): Promise<ApiResponse<OrdersResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.status && params.status !== "all") {
    searchParams.set("status", params.status);
  }
  if (params?.page !== undefined) {
    searchParams.set("page", String(params.page + 1)); // backend uses 1-based
  }
  if (params?.limit !== undefined) {
    searchParams.set("limit", String(params.limit));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<OrdersResponse>>(
    `/user/orders${qs ? `?${qs}` : ""}`,
  );
}
