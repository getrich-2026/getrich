import { apiFetch, type ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SubscribeRequest {
  plan_type: "monthly" | "yearly";
  payment_source: "wechat" | "alipay" | "bank" | "apple_pay" | "stripe";
  auto_renew?: boolean;
}

export interface SubscribeResult {
  subscription_id: string;
  status: "pending_payment";
  plan_type: "monthly" | "yearly";
  start_date: string;
  expire_date: string;
  payment: {
    order_id: string;
    amount: number;
    payment_source: string;
    expire_time: string;
  };
}

export interface UnsubscribeResult {
  strategy_id: string;
  status: "cancelled";
  access_until: string;
}

export interface SubscriptionStatus {
  is_subscribed: boolean;
  subscription_id: string | null;
  status: string | null;
  plan_type: string | null;
  start_date: string | null;
  expire_date: string | null;
  auto_renew: boolean;
  subscription_price: {
    monthly: number;
    yearly: number;
  };
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** Subscribe to a strategy. */
export function subscribe(
  strategyCode: string,
  body: SubscribeRequest,
): Promise<ApiResponse<SubscribeResult>> {
  return apiFetch<ApiResponse<SubscribeResult>>(
    `/strategies/${encodeURIComponent(strategyCode)}/subscribe`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** Unsubscribe from a strategy. */
export function unsubscribe(
  strategyCode: string,
  reason?: string,
): Promise<ApiResponse<UnsubscribeResult>> {
  const body = reason ? JSON.stringify({ reason }) : "{}";
  return apiFetch<ApiResponse<UnsubscribeResult>>(
    `/strategies/${encodeURIComponent(strategyCode)}/unsubscribe`,
    { method: "POST", body },
  );
}

/** Check subscription status for a strategy (no auth required). */
export function getSubscriptionStatus(
  strategyCode: string,
): Promise<ApiResponse<SubscriptionStatus>> {
  return apiFetch<ApiResponse<SubscriptionStatus>>(
    `/strategies/${encodeURIComponent(strategyCode)}/subscription`,
  );
}
