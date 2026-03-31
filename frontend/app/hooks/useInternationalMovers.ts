"use client";

import useSWR from "swr";

import { ApiError, fetcher } from "../lib/api";
import type { InternationalMoversResponse } from "../lib/types";

type UseInternationalMoversResult = {
  moversData?: InternationalMoversResponse;
  moversError: unknown;
  moversLoading: boolean;
  noMoversYet: boolean;
};

export function useInternationalMovers(limit: number): UseInternationalMoversResult {
  const { data, error, isLoading } = useSWR<InternationalMoversResponse>(
    `/api/international/movers/latest?limit=${limit}`,
    fetcher,
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  return {
    moversData: data,
    moversError: error,
    moversLoading: isLoading,
    noMoversYet: error instanceof ApiError && error.status === 404,
  };
}
