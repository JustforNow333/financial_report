"use client";

import { useMemo } from "react";
import useSWR from "swr";

import { ApiError, fetcher } from "../lib/api";
import type { IndustriesResponse, MoversResponse } from "../lib/types";

type UseMarketMoversResult = {
  industries: string[];
  industriesError: unknown;
  industriesLoading: boolean;
  moversData?: MoversResponse;
  moversError: unknown;
  moversLoading: boolean;
  noSnapshotsYet: boolean;
};

export function useMarketMovers(selectedIndustry: string, topCount: number): UseMarketMoversResult {
  const { data: industriesData, error: industriesError, isLoading: industriesLoading } = useSWR<
    IndustriesResponse
  >("/api/industries", fetcher, {
    revalidateOnFocus: false,
  });

  const moversPath = useMemo(() => {
    const params = new URLSearchParams({ limit: String(topCount) });
    if (selectedIndustry !== "All") {
      params.set("industry", selectedIndustry);
    }
    return `/api/movers/latest?${params.toString()}`;
  }, [selectedIndustry, topCount]);

  const { data: moversData, error: moversError, isLoading: moversLoading } = useSWR<MoversResponse>(
    moversPath,
    fetcher,
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  return {
    industries: industriesData?.industries ?? ["All"],
    industriesError,
    industriesLoading,
    moversData,
    moversError,
    moversLoading,
    noSnapshotsYet: moversError instanceof ApiError && moversError.status === 404,
  };
}
